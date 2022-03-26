from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject, QRunnable

class WorkerSignals(QObject):
    started = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)

class AsyncWorker(QRunnable):

    def __init__(self, fn, *args, **kwargs):
        super(AsyncWorker, self).__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        self.signals.started.emit(*self.args, **self.kwargs)
        self.fn(*self.args, **self.kwargs)
        self.signals.finished.emit(*self.args, **self.kwargs)

