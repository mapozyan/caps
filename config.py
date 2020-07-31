import multiprocessing
from string import ascii_lowercase

from PyQt5.Qt import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit
from calibre.utils.config import JSONConfig

prefs = JSONConfig('plugins/caps')

prefs.defaults['elasticsearch_url'] = 'localhost:9200'
prefs.defaults['pdftotext_path'] = 'pdftotext'
prefs.defaults['concurrency'] = multiprocessing.cpu_count()-1 or 1


class ConfigWidget(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        self.l = QVBoxLayout()
        self.setLayout(self.l)

        self.label1 = QLabel('ElasticSearch engine location:')
        self.l.addWidget(self.label1)

        self.msg1 = QLineEdit(self)
        self.msg1.setText(prefs['elasticsearch_url'])
        self.l.addWidget(self.msg1)
        self.label1.setBuddy(self.msg1)

        self.label2 = QLabel('Path to pdftotext tool:')
        self.l.addWidget(self.label2)

        self.msg2 = QLineEdit(self)
        self.msg2.setText(prefs['pdftotext_path'])
        self.l.addWidget(self.msg2)
        self.label2.setBuddy(self.msg2)

        self.label3 = QLabel('Number of parallel processes for text extraction:')
        self.l.addWidget(self.label3)

        self.msg3 = QLineEdit(self)
        self.msg3.setText(str(prefs['concurrency']))
        self.l.addWidget(self.msg3)
        self.label3.setBuddy(self.msg3)

    def save_settings(self):
        prefs['elasticsearch_url'] = self.msg1.text()
        prefs['pdftotext_path'] = self.msg2.text()
        try:
            prefs['concurrency'] = int(self.msg3.text())
        except Exception:
            pass
