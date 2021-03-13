import atexit
from calibre_plugins.caps.elasticsearch import Elasticsearch
from calibre_plugins.caps.subprocess_helper import subprocess_popen
from PyQt5 import Qt
from PyQt5.QtCore import Qt as QtCore
import os.path
import time

elasticsearch_process = None

def terminate_elasticsearch_process():
    global elasticsearch_process
    elasticsearch_process.terminate()

class LaunchMessageBox(Qt.QDialog):
    def __init__(self, parent, title, url, launch_path, *args, **kwargs):
        Qt.QDialog.__init__(self, parent, *args, **kwargs)
        self.setWindowTitle(title)
        self.setWindowFlags(QtCore.Window | QtCore.WindowTitleHint | QtCore.CustomizeWindowHint)

        self.url = url
        self.launch_path = launch_path

        self.layout = Qt.QVBoxLayout()
        self.setLayout(self.layout)

        icon = get_icons('images/icon.png')
        self.icon = Qt.QLabel(self)
        self.icon.setPixmap(icon.pixmap(42, 40))
        self.layout.addWidget(self.icon)

        self.info_label = Qt.QLabel('Launching ElasticSearch...')
        self.layout.addWidget(self.info_label)

        self.cancel_button = Qt.QPushButton('&Cancel', self)
        self.cancel_button.clicked.connect(self.cancel)
        self.layout.addWidget(self.cancel_button)

        self.visible = True

        Qt.QThreadPool.globalInstance().start(self.launch_elasticsearch)


    def launch_elasticsearch(self):
        global elasticsearch_process
        if elasticsearch_process:
            elasticsearch_process.terminate()
        try:
            elasticsearch_process = subprocess_popen([self.launch_path])
            atexit.register(terminate_elasticsearch_process)
            start_time = time.time()
            while self.visible and time.time() - start_time < 60:
                elastic_search_client = Elasticsearch([self.url], timeout=20.0)
                if elastic_search_client.ping():
                    break
                time.sleep(1)

            if self.visible:
                Qt.QDialog.reject(self)

        except Exception as ex:
            time.sleep(0.1)
            Qt.QDialog.reject(self)


    def cancel(self):
        self.visible = False

        global elasticsearch_process
        if elasticsearch_process:
            elasticsearch_process.terminate()
        Qt.QDialog.reject(self)


def get_elasticsearch_client(parent, title, url, launch_path):
    elastic_search_client = Elasticsearch([url], timeout=20.0)
    if launch_path and os.path.isfile(launch_path) and not elastic_search_client.ping():
        msgbox = LaunchMessageBox(parent, title, url, launch_path)
        msgbox.exec_()
    return elastic_search_client
