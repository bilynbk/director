
import os
import time
import math
import vtk
import PythonQt
from PythonQt import QtCore
from PythonQt import QtGui

from ddapp.timercallback import TimerCallback
from ddapp import midi

def getMainWindow():
    return _mainWindow

def quit():
    QtGui.QApplication.instance().quit()


def getDRCBase():
    return os.environ['DRC_BASE']


def getViewManager():
    return getMainWindow().viewManager()


def getDRCView():
    return getMainWindow().viewManager().findView('DRC View')


def getSpreadsheetView():
    return getMainWindow().viewManager().findView('Spreadsheet View')


def getCurrentView():
    return getMainWindow().viewManager().currentView()


def getCurrentRenderView():
    view = getCurrentView()
    if hasattr(view, 'camera'):
        return view


def getOutputConsole():
    return getMainWindow().outputConsole()


def getURDFModelDir():
    return os.path.join(getDRCBase(), 'software/models/mit_gazebo_models/mit_robot_drake')


def getNominalPoseMatFile():
    return os.path.join(getDRCBase(), 'software/drake/examples/Atlas/data/atlas_fp.mat')


def loadModelByName(name):
    filename = os.path.join(getURDFModelDir(), name)
    return getDRCView().loadURDFModel(filename)


def getDefaultDrakeModel():
    return getDRCView().models()[0]


def addWidgetToDock(widget):

    dock = QtGui.QDockWidget()
    dock.setWidget(widget)
    dock.setWindowTitle(widget.windowTitle)
    getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    getMainWindow().addWidgetToViewMenu(dock)


def resetCamera(viewDirection=None, view=None):

    view = view or getCurrentRenderView()
    assert(view)

    if viewDirection is not None:
        camera = view.camera()
        camera.SetPosition([0, 0, 0])
        camera.SetFocalPoint(viewDirection)
        camera.SetViewUp([0,0,1])

    view.resetCamera()
    view.render()


def displaySnoptInfo(info):
    getMainWindow().statusBar().showMessage('Info: %d' % info)


def toggleStereoRender():
    view = getCurrentRenderView()
    assert(view)

    renderWindow = view.renderWindow()
    renderWindow.SetStereoRender(not renderWindow.GetStereoRender())
    view.render()


def toggleCameraTerrainMode():

    view = getCurrentRenderView()
    assert(view)

    iren = view.renderWindow().GetInteractor()
    if isinstance(iren.GetInteractorStyle(), vtk.vtkInteractorStyleTerrain):
        iren.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
    else:
        iren.SetInteractorStyle(vtk.vtkInteractorStyleTerrain())
        view.camera().SetViewUp(0,0,1)

    view.render()


def setupToolBar():

    def onComboChanged(text):
        loadModelByName(text)


    combo = QtGui.QComboBox()
    combo.addItem('Load URDF...')
    combo.addItem('model.urdf')
    combo.addItem('model_minimal_contact.urdf')
    combo.addItem('model_minimal_contact_point_hands.urdf')
    combo.addItem('model_minimal_contact_fixedjoint_hands.urdf')

    combo.connect('currentIndexChanged(const QString&)', onComboChanged)
    toolbar = getMainWindow().toolBar()
    toolbar.addWidget(combo)


def showErrorMessage(message):
    QtGui.QMessageBox.warning(getMainWindow(), 'Error', message);


def startup(globals):

    global _mainWindow
    _mainWindow = globals['_mainWindow']

    if 'DRC_BASE' not in os.environ:
        showErrorMessage('DRC_BASE environment variable is not set')
        return

    if not os.path.isdir(getDRCBase()):
        showErrorMessage('DRC_BASE directory does not exist: ' + getDRCBase())
        return

    _mainWindow.connect('resetCamera()', resetCamera)
    _mainWindow.connect('toggleStereoRender()', toggleStereoRender)
    _mainWindow.connect('toggleCameraTerrainMode()', toggleCameraTerrainMode)

    #setupToolBar()

