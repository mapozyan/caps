import atexit
from calibre_plugins.caps.elasticsearch import Elasticsearch
from calibre_plugins.caps.subprocess_helper import subprocess_call, subprocess_popen
import json
from PyQt5 import QtCore, QtWidgets
from PyQt5.Qt import Qt
from PyQt5.QtCore import pyqtSlot
import os
import psutil
import time

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32


url = None
launch_path = None
elasticsearch_process = None
elasticsearch_subprocess = None
msgbox = None
ok = False

def terminate_elasticsearch_process():
    global launch_path
    global elasticsearch_process
    global elasticsearch_subprocess

    if elasticsearch_process:
        if os.name == 'nt':
            service_control_script = os.path.join(launch_path, 'bin', 'elasticsearch-service.bat')
            if os.path.isfile(service_control_script):
                subprocess_call([service_control_script, 'stop'])
            else:
                if elasticsearch_subprocess:
                    try:
                        children = [c for c in elasticsearch_subprocess.children(recursive=True)]
                        for child in children:
                            try:
                                child.terminate()
                            except Exception:
                                pass
                        try:
                            elasticsearch_subprocess.terminate()
                        except Exception:
                            pass
                    except Exception:
                        pass
        else:
            try:
                elasticsearch_process.terminate()
            except Exception:
                pass

    elasticsearch_process = None
    elasticsearch_subprocess = None

def worker(hwnd, lParam):
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == lParam:
        user32.ShowWindow(hwnd, 6)
    return True

def minimize(process):

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.EnumWindows.argtypes = [
        WNDENUMPROC,
        wintypes.LPARAM]

    user32.GetWindowTextLengthW.argtypes = [
        wintypes.HWND]

    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int]

    cb_worker = WNDENUMPROC(worker)
    if not user32.EnumWindows(cb_worker, process.pid):
        raise ctypes.WinError()


class Launcher(QtCore.QRunnable):

    @pyqtSlot()
    def run(self):
        global url
        global launch_path
        global elasticsearch_process
        global elasticsearch_subprocess
        global msgbox
        global ok

        try:

            if os.name == 'nt':
                service_control_script = os.path.join(launch_path, 'bin', 'elasticsearch-service.bat')
                if os.path.isfile(service_control_script):
                    subprocess_call([service_control_script, 'install'])
                    subprocess_popen([service_control_script, 'start'])
                    time.sleep(1)
                    elasticsearch_process = [proc for proc in psutil.process_iter() if 'elasticsearch-service' in proc.name()]
                    if elasticsearch_process:
                        elasticsearch_process = elasticsearch_process[0]
                    else:
                        elasticsearch_process = None
                else:
                    elasticsearch_process = subprocess_popen([os.path.join(launch_path, 'bin', 'elasticsearch.exe'), '-d'], shell=True)
                    time.sleep(1)
                    children = list(psutil.Process(elasticsearch_process.pid).children(recursive=False))
                    if children:
                        elasticsearch_subprocess = children[0]
                        minimize(elasticsearch_subprocess)
            else:
                elasticsearch_process = subprocess_popen([os.path.join(launch_path, 'bin', 'elasticsearch')])

            atexit.register(terminate_elasticsearch_process)
            start_time = time.time()
            while msgbox is not None and time.time() - start_time < 60:
                elastic_search_client = Elasticsearch([url], timeout=60.0)
                if elastic_search_client.ping(params={'request_timeout': 2.0}):
                    break
                time.sleep(1)

            if msgbox:
                QtWidgets.QDialog.reject(msgbox)
                ok = True

        except Exception as ex:
            time.sleep(0.1)
            if msgbox:
                msgbox.reason = 'Could not start ElasticSearch service. Please go to Options dialog and check your configuration.'
                QtWidgets.QDialog.reject(msgbox)

class LaunchMessageBox(QtWidgets.QDialog):

    def __init__(self, parent, title, *args, **kwargs):
        QtWidgets.QDialog.__init__(self, parent, *args, **kwargs)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint | Qt.WindowType.CustomizeWindowHint)

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        icon = get_icons('images/icon.png')
        self.icon = QtWidgets.QLabel(self)
        self.icon.setPixmap(icon.pixmap(42, 40))
        self.layout.addWidget(self.icon)

        self.info_label = QtWidgets.QLabel('Launching ElasticSearch...')
        self.layout.addWidget(self.info_label)

        self.cancel_button = QtWidgets.QPushButton('&Cancel', self)
        self.cancel_button.clicked.connect(self.cancel)
        self.layout.addWidget(self.cancel_button)

        self.reason = None

        launcher = Launcher()
        QtCore.QThreadPool.globalInstance().start(launcher)


    def cancel(self):
        try:
            terminate_elasticsearch_process()
        except Exception:
            pass
        self.reason = 'Operation cancelled'
        QtWidgets.QDialog.reject(self)


def get_elasticsearch_client(parent, title, _url, _launch_path):
    global url
    global launch_path
    global msgbox
    global ok

    reason = None
    elastic_search_client = Elasticsearch([_url], timeout=60.0)

    if not elastic_search_client.ping(params={'request_timeout': 2.0}):
        if _launch_path:
            if os.path.isdir(_launch_path):
                url = _url
                launch_path = _launch_path
                ok = False
                msgbox = LaunchMessageBox(parent, title)
                msgbox.exec_()

                if not ok:
                    elastic_search_client = None
                    reason = msgbox.reason
                msgbox = None

            else:
                elastic_search_client = None
                reason = 'Could not connect to ElasticSearch. Please go to Options dialog and check your configuration.'

        else:
            elastic_search_client = None
            reason = 'Could not connect to ElasticSearch. Please make sure that it\'s running or go to Options dialog and provide a valid path to ElasticSearch.'

    if elastic_search_client:
        ok = False
        start_time = time.time()

        while time.time() - start_time < 60:
            try:
                req = {
                    '_source': False,
                    'query': {
                        'simple_query_string': {
                            'query': '3f55fa2b-79ac-4f40-9244-6c0d7cbaa416'
                        }
                    }
                }
                elastic_search_client.search(index='library', body=json.dumps(req), ignore=[404])
                ok = True
                break

            except Exception as ex:
                time.sleep(1)

        if not ok:
            elastic_search_client = None
            reason = 'Timed out waiting for ElasticSearch to start.'

    return (elastic_search_client, reason)
