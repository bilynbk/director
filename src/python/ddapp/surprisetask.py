import os
import sys
import vtkAll as vtk
from ddapp import botpy
import math
import time
import types
import functools
import numpy as np

from ddapp import transformUtils
from ddapp import lcmUtils
from ddapp.timercallback import TimerCallback
from ddapp.asynctaskqueue import AsyncTaskQueue
from ddapp import objectmodel as om
from ddapp import visualization as vis
from ddapp import applogic as app
from ddapp.debugVis import DebugData
from ddapp import ikplanner
from ddapp.ikparameters import IkParameters
from ddapp import ioUtils
from ddapp.simpletimer import SimpleTimer
from ddapp.utime import getUtime
from ddapp import affordanceitems
from ddapp import robotstate
from ddapp import robotplanlistener
from ddapp import segmentation
from ddapp import planplayback
from ddapp import affordanceupdater
from ddapp import segmentationpanel
from ddapp import vtkNumpy as vnp
from ddapp import switchplanner

from ddapp.tasks.taskuserpanel import TaskUserPanel
from ddapp.tasks.taskuserpanel import ImageBasedAffordanceFit

import ddapp.tasks.robottasks as rt
import ddapp.tasks.taskmanagerwidget as tmw

import drc as lcmdrc
import copy

from PythonQt import QtCore, QtGui



class SurpriseTaskPlanner(object):

    def __init__(self, robotSystem):
        self.robotSystem = robotSystem
        self.robotModel = robotSystem.robotStateModel
        self.ikPlanner = robotSystem.ikPlanner
        self.lockBackForManip = False
        self.lockBaseForManip = True
        self.side = 'right'
        self.toolTipToHandFrame = robotSystem.ikPlanner.newPalmOffsetGraspToHandFrame(self.side, 0.1)


class ImageFitter(ImageBasedAffordanceFit):

    def __init__(self, switchPlanner):
        ImageBasedAffordanceFit.__init__(self, numberOfPoints=1)
        self.switchPlanner = switchPlanner
        self.fitFunc = None
        self.pickLineRadius = 0.05
        self.pickNearestToCamera = False

        self.useLocalPlaneFit = True
        self.useVoxelGrid = True

    def fit(self, polyData, points):
        if self.fitFunc:
            self.fitFunc(polyData, points)

    def fitSwitchBox(self, polyData, points):
        boxPosition = points[0]
        wallPoint = points[1]


        # find a frame that is aligned with wall
        searchRadius = 0.2
        planePoints, normal = segmentation.applyLocalPlaneFit(polyData, points[0], searchRadius=np.linalg.norm(points[1] - points[0]), searchRadiusEnd=1.0)

        obj = vis.updatePolyData(planePoints, 'wall plane points', color=[0,1,0], visible=False)
        obj.setProperty('Point Size', 7)

        viewDirection = segmentation.SegmentationContext.getGlobalInstance().getViewDirection()
        if np.dot(normal, viewDirection) < 0:
            normal = -normal

        origin = segmentation.computeCentroid(planePoints)

        zaxis = [0,0,1]
        xaxis = normal
        yaxis = np.cross(zaxis, xaxis)
        yaxis /= np.linalg.norm(yaxis)
        zaxis = np.cross(xaxis, yaxis)
        zaxis /= np.linalg.norm(zaxis)

        t = transformUtils.getTransformFromAxes(xaxis, yaxis, zaxis)

        # translate that frame to the box position
        t.PostMultiply()
        t.Translate(boxPosition)

        boxFrame = transformUtils.copyFrame(t)
        self.switchPlanner.spawnBoxAffordanceAtFrame(boxFrame)

class SurpriseTaskPanel(TaskUserPanel):

    def __init__(self, robotSystem):

        TaskUserPanel.__init__(self, windowTitle='Surprise Task')

        self.planner = SurpriseTaskPlanner(robotSystem)
        self.switchPlanner = switchplanner.SwitchPlanner(robotSystem)
        self.fitter = ImageFitter(self.switchPlanner)
        self.initImageView(self.fitter.imageView)

        self.addDefaultProperties()
        self.addButtons()
        self.addSwitchTasks()


    def test(self):
        print 'test'

    def addButtons(self):

        self.addManualSpacer()
        self.addManualButton('arms prep 1', self.switchPlanner.planArmsPrep1)
        self.addManualButton('arms prep 2', self.switchPlanner.planArmsPrep2)
        self.addManualButton('fit switch box', self.fitSwitchBox)
        self.addManualButton('spawn switch box affordance', self.switchPlanner.spawnBoxAffordance)
        self.addManualButton('spawn footstep frame', self.switchPlanner.spawnFootstepFrame)
        self.addManualButton('reset reach frame', self.switchPlanner.updateReachFrame)
        self.addManualButton('plan reach to reach frame', self.switchPlanner.planReach)

    def getSide(self):
        return self.params.getPropertyEnumValue('Hand').lower()

    def addDefaultProperties(self):
        self.params.addProperty('Hand', 0, attributes=om.PropertyAttributes(enumNames=['Left', 'Right']))
        self.params.setProperty('Hand', self.planner.side.capitalize())

    def onPropertyChanged(self, propertySet, propertyName):
        if propertyName == 'Hand':
            self.planner.side = self.getSide()

    def addTasks(self):

        # some helpers
        self.folder = None
        def addTask(task, parent=None):
            parent = parent or self.folder
            self.taskTree.onAddTask(task, copy=False, parent=parent)
        def addFunc(name, func, parent=None):
            addTask(rt.CallbackTask(callback=func, name=name), parent=parent)
        def addFolder(name, parent=None):
            self.folder = self.taskTree.addGroup(name, parent=parent)
            return self.folder

        def addManipTask(name, planFunc, userPrompt=False):

            prevFolder = self.folder
            addFolder(name, prevFolder)
            addFunc('plan', planFunc)
            if not userPrompt:
                addTask(rt.CheckPlanInfo(name='check manip plan info'))
            else:
                addTask(rt.UserPromptTask(name='approve manip plan', message='Please approve manipulation plan.'))
            addFunc('execute manip plan', self.drillDemo.commitManipPlan)
            addTask(rt.WaitForManipulationPlanExecution(name='wait for manip execution'))
            self.folder = prevFolder


        self.taskTree.removeAllTasks()
        side = self.getSide()

        ###############
        # add the tasks

        # prep
        # addFolder('Prep')
        # addTask(rt.CloseHand(name='close left hand', side='Left'))
        # addTask(rt.CloseHand(name='close right hand', side='Right'))
        self.addSwitchTasks()

    def addSwitchTasks(self):

        # some helpers
        self.folder = None
        def addTask(task, parent=None):
            parent = parent or self.folder
            self.taskTree.onAddTask(task, copy=False, parent=parent)
        def addFunc(name, func, parent=None):
            addTask(rt.CallbackTask(callback=func, name=name), parent=parent)
        def addFolder(name, parent=None):
            self.folder = self.taskTree.addGroup(name, parent=parent)
            return self.folder

        def addManipTask(name, planFunc, userPrompt=False):

            prevFolder = self.folder
            addFolder(name, prevFolder)
            addFunc('plan', planFunc)
            if not userPrompt:
                addTask(rt.CheckPlanInfo(name='check manip plan info'))
            else:
                addTask(rt.UserPromptTask(name='approve manip plan', message='Please approve manipulation plan.'))
            addFunc('execute manip plan', self.switchPlanner.commitManipPlan)
            addTask(rt.WaitForManipulationPlanExecution(name='wait for manip execution'))
            self.folder = prevFolder


        self.taskTree.removeAllTasks()
        side = self.getSide()

        addFolder('Fit Box Affordance')
        addFunc('fit switch box affordance', self.fitSwitchBox)
        addTask(rt.UserPromptTask(name='verify/adjust affordance', message='verify/adjust affordance.'))

        # walk to drill
        addFolder('Walk')
        addFunc('plan footstep frame', self.switchPlanner.spawnFootstepFrame)
        addTask(rt.RequestFootstepPlan(name='plan walk to drill', stanceFrameName='switch box stance frame'))
        addTask(rt.UserPromptTask(name='approve footsteps', message='Please approve footstep plan.'))
        addTask(rt.CommitFootstepPlan(name='walk to switch box', planName='switch box stance frame footstep plan'))
        addTask(rt.WaitForWalkExecution(name='wait for walking'))

        armsUp = addFolder('Arms Up')
        addManipTask('Arms Up 1', self.switchPlanner.planArmsPrep1, userPrompt=True)
        self.folder = armsUp
        addManipTask('Arms Up 2', self.switchPlanner.planArmsPrep2, userPrompt=True)

        reach = addFolder('Reach')
        addFunc('update reach frame', self.switchPlanner.updateReachFrame)
        addTask(rt.UserPromptTask(name='adjust frame', message='adjust reach frame if necessary'))
        addManipTask('reach above box', self.switchPlanner.planReach, userPrompt=True)

        teleop = addFolder('Teleop')
        addTask(rt.UserPromptTask(name='wait for teleop', message='continue when finished with task.'))


        armsDown = addFolder('Arms Down')
        addManipTask('Arms Down 1', self.switchPlanner.planArmsPrep2, userPrompt=True)
        self.folder = armsDown
        addTask(rt.CloseHand(name='close left hand', side='Right'))
        self.folder = armsDown
        addManipTask('Arms Down 2', self.switchPlanner.planArmsPrep1, userPrompt=True)
        self.folder = armsDown
        addManipTask('plan nominal', self.switchPlanner.planNominal, userPrompt=True)


    def fitSwitchBox(self):
        print 'fitting switch box'
        self.fitter.imagePicker.numberOfPoints = 2
        self.fitter.pointCloudSource = 'lidar'
        self.fitter.fitFunc = self.fitter.fitSwitchBox




