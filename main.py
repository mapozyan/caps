import datetime
import dateutil.tz
import functools
import json
import os
import platform
import sys
import threading
import time
from timeit import default_timer as timer

import calibre
import calibre.ptempfile
from calibre.utils.config_base import json_dumps
from calibre_plugins.caps import CapsPlugin
from calibre_plugins.caps.async_worker import AsyncWorker
from calibre_plugins.caps.config import prefs, ARCHIVE_FORMATS
from calibre_plugins.caps.elasticsearch_helper import get_elasticsearch_client
from calibre_plugins.caps.subprocess_helper import subprocess_call
from PyQt5 import Qt, QtWidgets
from PyQt5.QtCore import Qt as QtCore

TITLE = 'Power Search'

SEARCH_HISTORY_ITEMS = 10

if False:
    get_resources = lambda x: x
    get_icons = lambda x: x

def is_exe(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

def which(program):
    fpath = os.path.split(program)[0]
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ['PATH'].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

def concat(book_id, format):
    return '{}:{}'.format(book_id, format)

class ScrollMessageBox(Qt.QDialog):
    def __init__(self, items, width, height, *args, **kwargs):
        Qt.QDialog.__init__(self, *args, **kwargs)
        self.setWindowTitle(TITLE)
        self.layout = Qt.QVBoxLayout()
        self.setLayout(self.layout)

        icon = get_icons('images/icon.png')
        self.icon = Qt.QLabel(self)
        self.icon.setPixmap(icon.pixmap(85, 80))
        self.layout.addWidget(self.icon)

        scroll = Qt.QScrollArea(self)
        scroll.setWidgetResizable(True)
        self.content = Qt.QWidget()
        scroll.setWidget(self.content)
        lay = Qt.QVBoxLayout(self.content)
        for item in items:
            lay.addWidget(Qt.QLabel(item, self))
        self.layout.addWidget(scroll)
        self.ok_button = Qt.QPushButton('&OK', self)
        self.ok_button.setIcon(get_icons('images/ok.png'))
        self.ok_button.clicked.connect(self.close)
        self.ok_layout = Qt.QHBoxLayout()
        self.ok_layout.addStretch()
        self.ok_layout.addWidget(self.ok_button)
        self.layout.addLayout(self.ok_layout)
        self.setStyleSheet('QScrollArea{{min-width: {}px; min-height: {}px}}'.format(width, height))

class SearchDialog(Qt.QDialog):

    def __init__(self, plugin, gui, icon):

        Qt.QDialog.__init__(self, gui)
        self.plugin = plugin
        self.gui = gui
        self.full_db = gui.current_db
        self.db = gui.current_db.new_api

        self.elastic_search_client = None
        self.conversion_time_dict = {}

        self.setWindowTitle(TITLE)
        self.setWindowIcon(icon)
        self.setWindowFlags(QtCore.Window | QtCore.WindowTitleHint | QtCore.CustomizeWindowHint)

        self.layout = Qt.QVBoxLayout()
        self.setLayout(self.layout)

        self.search_label = Qt.QLabel('Enter &text to search in content')
        self.layout.addWidget(self.search_label)

        self.search_text_layout = Qt.QHBoxLayout()

        self.search_textbox = Qt.QComboBox(self)
        self.search_textbox.setMinimumWidth(400)
        self.search_textbox.setEditable(True)
        self.search_textbox.setInsertPolicy(Qt.QComboBox.NoInsert)
        for _, value in sorted(prefs.get('search_lru', {}).items()):
            self.search_textbox.addItem(value)
        self.search_textbox.setEditText('')
        self.search_textbox.editTextChanged.connect(self.on_search_text_changed)
        self.search_label.setBuddy(self.search_textbox)
        self.search_text_layout.addWidget(self.search_textbox)

        self.search_help_button = Qt.QPushButton('?', self)
        fixed_size_policy = self.search_help_button.sizePolicy()
        fixed_size_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Fixed)
        self.search_help_button.setSizePolicy(fixed_size_policy)
        self.search_help_button.clicked.connect(self.on_search_help)
        self.search_text_layout.addWidget(self.search_help_button)

        self.layout.addLayout(self.search_text_layout)

        self.search_button_layout = Qt.QHBoxLayout()
        self.search_button_layout.setSpacing(0)

        self.search_button = Qt.QPushButton('&Search', self)
        self.search_button.setEnabled(False)
        self.search_button.setDefault(True)
        self.search_button.clicked.connect(self.on_search_all)
        self.search_button_layout.addWidget(self.search_button)

        self.custom_search_button = Qt.QPushButton('', self)
        self.custom_search_button.setMaximumWidth(self.custom_search_button.iconSize().width())
        self.custom_search_button.setEnabled(False)
        self.search_button_layout.addWidget(self.custom_search_button)

        self.custom_search_button_dropdown = QtWidgets.QMenu(self)
        self.custom_search_button_dropdown.addAction('Search in the whole library', self.on_search_all)
        self.custom_search_button_dropdown.addAction('Search in selected books', self.on_search_selected)
        self.custom_search_button.setMenu(self.custom_search_button_dropdown)

        self.layout.addLayout(self.search_button_layout)

        self.cancel_button = Qt.QPushButton('&Cancel', self)
        self.cancel_button.clicked.connect(self.on_cancel)
        self.cancel_button.setVisible(False)
        self.layout.addWidget(self.cancel_button)

        self.status_label = Qt.QLabel()
        self.status_label.setAlignment(QtCore.AlignCenter)
        self.layout.addWidget(self.status_label)

        self.progress_bar = Qt.QProgressBar(self)
        self.progress_bar.setVisible(False)
        retain_size_policy = self.progress_bar.sizePolicy()
        retain_size_policy.setRetainSizeWhenHidden(True)
        self.progress_bar.setSizePolicy(retain_size_policy)
        self.layout.addWidget(self.progress_bar)

        self.details_button = Qt.QPushButton('&Details', self)
        self.details_button.setVisible(False)
        retain_size_policy = self.details_button.sizePolicy()
        retain_size_policy.setRetainSizeWhenHidden(True)
        self.details_button.setSizePolicy(retain_size_policy)
        self.details_button.setFlat(True)
        self.details_button.setStyleSheet('text-align: left')
        icon = get_icons('images/right-arrow.png')
        self.details_button.setIcon(icon)
        self.details_button.clicked.connect(self.on_details)
        self.layout.addWidget(self.details_button)

        self.details = Qt.QListWidget(self)
        self.details.setVisible(False)
        self.layout.addWidget(self.details)

        self.layout.addStretch()

        self.reindex_layout = Qt.QHBoxLayout()

        self.reindex_button = Qt.QPushButton('Reindex &new books', self)
        self.reindex_button.clicked.connect(self.on_reindex)
        self.reindex_layout.addWidget(self.reindex_button)

        self.reindex_all_button = Qt.QPushButton('Reindex &all books', self)
        self.reindex_all_button.clicked.connect(self.on_reindex_all)
        self.reindex_layout.addWidget(self.reindex_all_button)

        self.layout.addLayout(self.reindex_layout)

        self.conf_button = Qt.QPushButton('&Options...', self)
        self.conf_button.clicked.connect(self.on_config)
        self.layout.addWidget(self.conf_button)

        self.readme_button = Qt.QPushButton('&Readme...', self)
        self.readme_button.clicked.connect(self.on_readme)
        self.layout.addWidget(self.readme_button)

        self.close_button = Qt.QPushButton('&Close', self)
        self.close_button.clicked.connect(self.close)
        self.layout.addWidget(self.close_button)

        self.thread_pool = Qt.QThreadPool()

        self.add_workers_submitted = 0
        self.add_workers_complete = 0

        self.delete_workers_submitted = 0
        self.delete_workers_complete = 0

        self.first_paint = True

        self.pdftotext_full_path = None

        self.ids = None

        if 'version' not in prefs:
            file_formats = set(prefs['file_formats'].split(',') + ARCHIVE_FORMATS)
            prefs['file_formats'] = ','.join(file_formats)
            prefs['version'] = CapsPlugin.version

    def _get_pdftotext_full_path(self):

        if self.pdftotext_full_path is None:
            pdftotext = prefs['pdftotext_path']

            if is_exe(pdftotext):
                self.pdftotext_full_path = pdftotext
            elif os.path.sep not in pdftotext:
                self.pdftotext_full_path = which(pdftotext)

        return self.pdftotext_full_path

    def on_search_all(self):
        self.ids = None
        self.on_search()

    def on_search_selected(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        self.ids = list(map(self.gui.library_view.model().id, rows))
        self.on_search()

    def on_search(self):
        self.status_label.setText('')
        self._manage_lru()
        if prefs['autoindex']:
            self._reindex(self.do_search)
        else:
            self.do_search()

    def _manage_lru(self):
        current_text = self.search_textbox.currentText()
        for i in range(self.search_textbox.count()):
            if self.search_textbox.itemText(i) == current_text:
                self.search_textbox.removeItem(i)
                break
        if self.search_textbox.count() >= SEARCH_HISTORY_ITEMS:
            self.search_textbox.removeItem(self.search_textbox.count() - 1)
        self.search_textbox.setEditText(current_text)
        self.search_textbox.insertItem(0, current_text)
        search_lru = {}
        for i in range(self.search_textbox.count()):
            try:
                text = self.search_textbox.itemText(i)
                json_dumps(text)
                search_lru[i] = text
            except TypeError as ex:
                pass
        prefs['search_lru'] = search_lru

    def _reindex(self, completion_proc=None):
        # Start conversion time dictionaries
        self.timer_start = {}
        self.timer_end = {}
        self.conversion_time_dict = {}

        # Set timer for the whole indexing
        self.timer_total_start = timer()

        self._set_searching_mode()

        self.canceled = threading.Event()

        self.elastic_search_client, reason = get_elasticsearch_client(self, TITLE, prefs['elasticsearch_url'], prefs['elasticsearch_launch_path'])

        if not self.elastic_search_client:
            from calibre.gui2 import error_dialog
            error_dialog(
                self,
                TITLE,
                reason,
                show=True)
            self._set_idle_mode()
            return

        if not self.elastic_search_client.ping():
            from calibre.gui2 import error_dialog
            error_dialog(
                self,
                TITLE,
                'Could not connect to ElasticSearch cluster. Please make sure that it\'s running.',
                show=True)
            self._set_idle_mode()
            return

        index_state = prefs.get(self.db.library_id, {}).get('index_state', {})

        all_formats = set()
        self.update_list = []
        self.delete_list = []

        epoch = datetime.datetime(1, 1, 1, 0, 0, tzinfo=dateutil.tz.tzutc())

        file_formats = prefs['file_formats'].split(',')
        for book_id in self.db.all_book_ids():
            if 'noindex' not in self.db.get_metadata(book_id).tags:
                for format in self.db.formats(book_id):
                    if format in file_formats:
                        last_modified = self.db.format_metadata(book_id, format)['mtime']
                        key = concat(book_id, format)
                        all_formats.add(key)
                        if index_state.get(key, epoch) < last_modified:
                            self.update_list.append({
                                'book_id': book_id,
                                'format': format,
                                'metadata': str(self.db.get_metadata(book_id)),
                                'input': self.db.format_abspath(book_id, format),
                                'last_modified': last_modified,
                                'completion_proc': completion_proc
                            })

        self.delete_list = [k for k in index_state.keys() if k not in all_formats]

        if len(self.update_list) + len(self.delete_list) > 0:
            self.thread_pool.setMaxThreadCount(prefs['concurrency'])
            self.add_workers_submitted = len(self.update_list)
            self.add_workers_complete = 0
            self.delete_workers_submitted = len(self.delete_list)
            self.delete_workers_complete = 0
            self.progress_bar.setMaximum(len(self.update_list) + len(self.delete_list) / 20)
            for curr in self.update_list:
                worker = AsyncWorker(self.add_book, curr)
                worker.signals.started.connect(self.add_worker_started)
                worker.signals.finished.connect(self.add_worker_complete)
                self.thread_pool.start(worker)
            for curr in self.delete_list:
                curr = {'book_id': curr, 'completion_proc': completion_proc}
                worker = AsyncWorker(self.delete_book, curr)
                worker.signals.finished.connect(self.delete_worker_complete)
                self.thread_pool.start(worker)
        else:
            self._set_idle_mode()
            if completion_proc:
                completion_proc()

    def add_worker_started(self, args):
        id = concat(args['book_id'], args['format'])
        item = Qt.QListWidgetItem('Converting {}'.format(args['input']))
        item.setData(QtCore.UserRole, id)
        self.details.addItem(item)
        # Sets the initial timer for conversion
        self.timer_start.update({id: timer()})

    def add_worker_complete(self, args):
        id = concat(args['book_id'], args['format'])
        for i in range(self.details.count()):
            item = self.details.item(i)
            curr_id = item.data(QtCore.UserRole)
            if curr_id == id:
                self.details.takeItem(i)
                # Get the conversion time for this book
                self.timer_end.update({id: timer()})
                self.conversion_time_seconds = self.timer_end[id] - self.timer_start[id]
                self.conversion_time = datetime.timedelta(seconds=self.conversion_time_seconds)
                # print('Book {} converted in {}.'.format(id, self.conversion_time))
                # Add it to a dictionary with all the converted books
                self.conversion_time_dict.update({id: self.conversion_time_seconds})
                break
        if not self.canceled.is_set():
            self.progress_bar.setValue(self.progress_bar.value() + 1)
        self.add_workers_complete += 1
        self._check_work_complete(args['completion_proc'])

    def delete_worker_complete(self, args):
        if not self.canceled.is_set():
            if self.delete_workers_complete % 20 == 0:
                self.progress_bar.setValue(self.progress_bar.value() + 1)
        self.delete_workers_complete += 1
        self._check_work_complete(args['completion_proc'])

    def _check_work_complete(self, completion_proc):
        if self.add_workers_complete != self.add_workers_submitted or self.delete_workers_complete != self.delete_workers_submitted:
            return

        if self.canceled.is_set():
            self.status_label.setText('Cancelled')
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setValue(self.progress_bar.maximum())

        self.workers_submitted = 0
        self.workers_complete = 0

        self._set_idle_mode()
        if completion_proc:
            completion_proc()

    def convert_book(self, input, format):
        if format in ARCHIVE_FORMATS:
            content = []
            try:
                file_formats = prefs['file_formats'].split(',')
                directory = calibre.ptempfile.PersistentTemporaryDirectory()
                calibre.extract(input, directory)
                for curr_dir, _, files in os.walk(directory):
                    for f in files:
                        for fmt in file_formats:
                            if f.upper().endswith('.' + fmt):
                                content += self.convert_book(os.path.join(curr_dir, f), fmt)
            except Exception as ex:
                print(ex)

            return content

        output = self.plugin.temporary_file(suffix='.txt').name
        done = False
        if format == 'PDF':
            pdftotext_full_path = self._get_pdftotext_full_path()
            if pdftotext_full_path:
                subprocess_call([pdftotext_full_path, '-enc', 'UTF-8', input, output])
                # print('Book {} converted with pdfttotext.'.format(id))
                done = True
        if not done:
            os_name = platform.system()
            ebook_convert_path = '/Applications/calibre.app/Contents/MacOS/ebook-convert' if os_name == 'Darwin' else 'ebook-convert'
            subprocess_call([ebook_convert_path, input, output])
        # print('Book {} converted to plaintext'.format(id))

        if sys.version_info[0] >= 3:
            content = open(output, errors='ignore').readlines()
        else:
            content = open(output).readlines()
        return content

    def add_book(self, args):

        try:
            if self.canceled.is_set():
                return
            id = concat(args['book_id'], args['format'])
            print('Book {} start processing: {}'.format(id, args['input']))
            content = self.convert_book(args['input'], args['format'])

            doc = {
                'metadata': args['metadata'],
                'content': content
            }
            res = self.elastic_search_client.index(index='library', id=id, body=doc)
            print('Book {} "{}" in index'.format(id, res['result']))

            # print('Book {} "{}" in index'.format(id, args['input']))

            if 'index_state' not in prefs[self.db.library_id]:
                prefs[self.db.library_id]['index_state'] = {}
            prefs[self.db.library_id]['index_state'][id] = args['last_modified']
            prefs.commit()



        except Exception as ex:
            print(ex)

    def delete_book(self, args):
        try:
            self.elastic_search_client.delete(index='library', id=args['book_id'], ignore=[404])
            # print('Deleted {}'.format(id['book_id']))

            if 'index_state' in prefs[self.db.library_id]:
                del prefs[self.db.library_id]['index_state'][args['book_id']]
                prefs.commit()

        except Exception as ex:
            print(ex)

    def do_search(self):

        req = {
            '_source': False,
            'query': {
                'simple_query_string': {
                    'query': self.search_textbox.currentText(),
                    'default_operator': 'AND'
                }
            }
        }

        if not self.elastic_search_client:
            self.elastic_search_client, reason = get_elasticsearch_client(self, TITLE, prefs['elasticsearch_url'], prefs['elasticsearch_launch_path'])

        if not self.elastic_search_client:
            from calibre.gui2 import error_dialog
            error_dialog(
                self,
                TITLE,
                reason,
                show=True)
            self._set_idle_mode()
            return

        res = self.elastic_search_client.search(index='library', body=json.dumps(req))

        hits_number = res['hits']['total']['value']
        page_size = len(res['hits']['hits'])

        matched_ids = set()

        for i in range(hits_number):
            if not res['hits']['hits']:
                req['from'] = i
                req['size'] = page_size
                res = self.elastic_search_client.search(index='library', body=json.dumps(req))

            curr = res['hits']['hits'].pop(0)
            id = int(curr['_id'].split(':')[0])
            if self.ids is None or id in self.ids:
                matched_ids.add(id)

        self.status_label.setText('Found {} books'.format(len(matched_ids)))
        self.full_db.set_marked_ids(matched_ids)
        self.gui.search.setEditText('marked:true')
        self.gui.search.do_search()

        # If new books are found, it shows which file took the longest and also the total time of conversion/indexing
        if self.conversion_time_dict:
            self.max_conversion_time_seconds = self.conversion_time_dict[
                max(self.conversion_time_dict, key=self.conversion_time_dict.get)]
            self.max_conversion_time = datetime.timedelta(seconds=self.max_conversion_time_seconds)
            print('Book {} took the longest time to convert: {}'.format(
                max(self.conversion_time_dict, key=self.conversion_time_dict.get), self.max_conversion_time))
            self.timer_total_end = timer()
            self.timer_total = datetime.timedelta(seconds=(self.timer_total_end - self.timer_total_start))
            print('Total time for conversion/indexing: {}'.format(self.timer_total))

    def _set_idle_mode(self):
        self.search_textbox.setEnabled(True)
        self.search_help_button.setEnabled(True)
        self.reindex_button.setEnabled(True)
        self.reindex_all_button.setEnabled(True)
        self.conf_button.setEnabled(True)
        self.search_button.setVisible(True)
        self.custom_search_button.setVisible(True)
        self.readme_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.cancel_button.setText('&Cancel')
        self.progress_bar.setVisible(False)
        self.details_button.setVisible(False)
        self.details.setVisible(False)
        self.search_textbox.setFocus(QtCore.OtherFocusReason)

    def _set_searching_mode(self):
        self.search_textbox.setEnabled(False)
        self.search_help_button.setEnabled(False)
        self.reindex_button.setEnabled(False)
        self.reindex_all_button.setEnabled(False)
        self.search_button.setVisible(False)
        self.custom_search_button.setVisible(False)
        self.readme_button.setEnabled(False)
        self.conf_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)
        self.details_button.setVisible(True)
        icon = get_icons('images/right-arrow.png')
        self.details_button.setIcon(icon)

    def on_details(self):
        self.details.setVisible(not self.details.isVisible())
        icon = get_icons('images/down-arrow.png' if self.details.isVisible() else 'images/right-arrow.png')
        self.details_button.setIcon(icon)

    def on_cancel(self):
        self.status_label.setText('')
        self.canceled.set()
        self.cancel_button.setText('Cancelling...')
        self.cancel_button.setEnabled(False)

    def on_search_text_changed(self, text):
        self.search_button.setEnabled(text != '')
        self.custom_search_button.setEnabled(text != '')

    def reject(self):
        if self.close_button.isEnabled():
            self.status_label.setText('')
            prefs['geometry'] = self.saveGeometry()
            Qt.QDialog.reject(self)

    def on_readme(self):
        text = get_resources('README.txt')
        text = '<html><body><pre>{}</pre></body></html>'.format(text.decode('utf-8'))
        msgbox = ScrollMessageBox([text], 850, 500)
        msgbox.exec_()

    def on_reindex(self):
        self.status_label.setText('')
        self._reindex()

    def on_reindex_all(self):
        from calibre.gui2 import question_dialog

        if question_dialog(self, TITLE, 'You are about to rebuild all fulltext search index. This process might take a while. Are you sure?', default_yes=False):

            self.elastic_search_client, reason = get_elasticsearch_client(self, TITLE, prefs['elasticsearch_url'], prefs['elasticsearch_launch_path'])

            if not self.elastic_search_client:
                from calibre.gui2 import error_dialog
                error_dialog(
                    self,
                    TITLE,
                    reason,
                    show=True)
                return

            if not self.elastic_search_client.ping():
                from calibre.gui2 import error_dialog
                error_dialog(
                    self,
                    TITLE,
                    'Could not connect to ElasticSearch cluster. Please make sure that it\'s running.',
                    show=True)
                return

            self.status_label.setText('')

            self.elastic_search_client.indices.delete(index='library', ignore=[400, 404])

            prefs[self.db.library_id] = {'index_state': {}}
            prefs.commit()

            self._reindex()

    def on_config(self):
        ok_pressed = self.plugin.do_user_config(parent=self)
        if ok_pressed:
            self.pdftotext_full_path = None
            pdftotext_full_path = self._get_pdftotext_full_path()
            if not pdftotext_full_path:
                from calibre.gui2 import error_dialog
                error_dialog(
                    self,
                    TITLE,
                    'Could not find pdftotext tool. Please make sure that the path "{}" is correct.'.format(prefs['pdftotext_path']),
                    show=True)

    def on_search_help(self):
        text = get_resources('USAGE.txt')
        text = '<html><body><pre>{}</pre></body></html>'.format(text.decode('utf-8'))

        msgbox = ScrollMessageBox([text], 850, 350)
        msgbox.exec_()

    def paintEvent(self, event):
        if self.first_paint:
            if 'geometry' in prefs:
                self.restoreGeometry(prefs['geometry'])
            self.first_paint = False
        return Qt.QDialog.paintEvent(self, event)

    def clear_lru(self):
        self.search_textbox.clear()
