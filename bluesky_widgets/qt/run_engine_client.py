import ast
import inspect
import time
import pprint
import copy

from qtpy.QtWidgets import (
    QWidget,
    QGroupBox,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QHeaderView,
    QAbstractItemView,
    QTextEdit,
    QTabWidget,
    QRadioButton,
    QButtonGroup,
    QComboBox,
    QSizePolicy,
    QLineEdit,
    QCheckBox,
)
from qtpy.QtCore import Qt, Signal, Slot, QTimer
from qtpy.QtGui import QFontMetrics, QPalette, QBrush, QColor

from bluesky_widgets.qt.threading import FunctionWorker
from bluesky_queueserver.manager.profile_ops import _construct_parameters


class QtReManagerConnection(QWidget):
    signal_update_widget = Signal(object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._lb_connected = QLabel("OFF")

        self._pb_re_manager_connect = QPushButton("Connect")
        self._pb_re_manager_connect.clicked.connect(self._pb_re_manager_connect_clicked)

        self._pb_re_manager_disconnect = QPushButton("Disconnect")
        self._pb_re_manager_disconnect.clicked.connect(
            self._pb_re_manager_disconnect_clicked
        )

        self._group_box = QGroupBox("Queue Server")

        vbox = QVBoxLayout()
        vbox.addWidget(self._lb_connected, alignment=Qt.AlignHCenter)
        vbox.addWidget(self._pb_re_manager_connect)
        vbox.addWidget(self._pb_re_manager_disconnect)

        self._group_box.setLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(self._group_box)
        self.setLayout(vbox)

        # Thread used to initiate periodic status updates
        self._thread = None
        self.updates_activated = False
        self.update_period = 1  # Status update period in seconds

        self._update_widget_states()
        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widget.connect(self.slot_update_widgets)

    def _update_widget_states(self):
        self._pb_re_manager_connect.setEnabled(not self.updates_activated)
        self._pb_re_manager_disconnect.setEnabled(self.updates_activated)

        # We don't know if the server is online or offline:
        self._lb_connected.setText("-----")

    def on_update_widgets(self, event):
        is_connected = event.is_connected
        self.signal_update_widget.emit(is_connected)

    @Slot(object)
    def slot_update_widgets(self, is_connected):
        # 'is_connected' may take values None, True and False
        text = "-----"
        if is_connected is True:
            text = "ONLINE"
        elif is_connected is False:
            text = "OFFLINE"
        self._lb_connected.setText(text)

    def _pb_re_manager_connect_clicked(self):
        self.updates_activated = True
        self.model.clear_connection_status()
        self._update_widget_states()
        self.model.manager_connecting_ops()
        self._start_thread()

    def _pb_re_manager_disconnect_clicked(self):
        self.updates_activated = False

    def _start_thread(self):
        self._thread = FunctionWorker(self._reload_status)
        self._thread.finished.connect(self._reload_complete)
        self._thread.start()

    def _reload_complete(self):
        if self.updates_activated:
            self._start_thread()
        else:
            self.model.clear_connection_status()
            self._update_widget_states()

    def _reload_status(self):
        self.model.load_re_manager_status()
        time.sleep(self.update_period)


class QtReEnvironmentControls(QWidget):
    signal_update_widget = Signal(bool, object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._pb_env_open = QPushButton("Open")
        self._pb_env_open.setEnabled(False)
        self._pb_env_open.clicked.connect(self._pb_env_open_clicked)

        self._pb_env_close = QPushButton("Close")
        self._pb_env_close.setEnabled(False)
        self._pb_env_close.clicked.connect(self._pb_env_close_clicked)

        self._pb_env_destroy = QPushButton("Destroy")
        self._pb_env_destroy.setEnabled(False)
        self._pb_env_destroy.clicked.connect(self._pb_env_destroy_clicked)

        self._group_box = QGroupBox("Environment")

        vbox = QVBoxLayout()
        vbox.addWidget(self._pb_env_open)
        vbox.addWidget(self._pb_env_close)
        vbox.addWidget(self._pb_env_destroy)

        self._group_box.setLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(self._group_box)
        self.setLayout(vbox)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widget.connect(self.slot_update_widgets)

    def on_update_widgets(self, event):
        is_connected = bool(event.is_connected)
        status = event.status
        self.signal_update_widget.emit(is_connected, status)

    @Slot(bool, object)
    def slot_update_widgets(self, is_connected, status):
        # 'is_connected' takes values True, False
        worker_exists = status.get("worker_environment_exists", False)
        manager_state = status.get("manager_state", None)
        self._pb_env_open.setEnabled(
            is_connected and not worker_exists and (manager_state == "idle")
        )
        self._pb_env_close.setEnabled(
            is_connected and worker_exists and (manager_state == "idle")
        )
        self._pb_env_destroy.setEnabled(is_connected and worker_exists)

    def _pb_env_open_clicked(self):
        try:
            self.model.environment_open()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_env_close_clicked(self):
        try:
            self.model.environment_close()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_env_destroy_clicked(self):
        try:
            self.model.environment_destroy()
        except Exception as ex:
            print(f"Exception: {ex}")


class QtReQueueControls(QWidget):
    signal_update_widget = Signal(bool, object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._lb_queue_state = QLabel("STOPPED")

        self._pb_queue_start = QPushButton("Start")
        self._pb_queue_start.setEnabled(False)
        self._pb_queue_start.clicked.connect(self._pb_queue_start_clicked)

        self._pb_queue_stop = QPushButton("Stop")
        self._pb_queue_stop.setEnabled(False)
        self._pb_queue_stop.setCheckable(True)
        self._pb_queue_stop.clicked.connect(self._pb_queue_stop_clicked)

        self._group_box = QGroupBox("Queue")

        vbox = QVBoxLayout()
        vbox.addWidget(self._lb_queue_state, alignment=Qt.AlignHCenter)
        vbox.addWidget(self._pb_queue_start)
        vbox.addWidget(self._pb_queue_stop)

        self._group_box.setLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(self._group_box)
        self.setLayout(vbox)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widget.connect(self.slot_update_widgets)

    def on_update_widgets(self, event):
        is_connected = bool(event.is_connected)
        status = event.status
        self.signal_update_widget.emit(is_connected, status)

    @Slot(bool, object)
    def slot_update_widgets(self, is_connected, status):
        # 'is_connected' takes values True, False
        worker_exists = status.get("worker_environment_exists", False)
        running_item_uid = status.get("running_item_uid", None)
        queue_stop_pending = status.get("queue_stop_pending", False)

        s = "RUNNING" if running_item_uid else "STOPPED"
        self._lb_queue_state.setText(s)

        self._pb_queue_start.setEnabled(
            is_connected and worker_exists and not bool(running_item_uid)
        )
        self._pb_queue_stop.setEnabled(
            is_connected and worker_exists and bool(running_item_uid)
        )
        self._pb_queue_stop.setChecked(queue_stop_pending)

    def _pb_queue_start_clicked(self):
        try:
            self.model.queue_start()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_queue_stop_clicked(self):
        try:
            if self._pb_queue_stop.isChecked():
                self.model.queue_stop()
            else:
                self.model.queue_stop_cancel()
        except Exception as ex:
            print(f"Exception: {ex}")


class QtReExecutionControls(QWidget):
    signal_update_widget = Signal(bool, object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._pb_plan_pause_deferred = QPushButton("Pause: Deferred")
        self._pb_plan_pause_deferred.setEnabled(False)
        self._pb_plan_pause_deferred.clicked.connect(
            self._pb_plan_pause_deferred_clicked
        )

        self._pb_plan_pause_immediate = QPushButton("Pause: Immediate")
        self._pb_plan_pause_immediate.setEnabled(False)
        self._pb_plan_pause_immediate.clicked.connect(
            self._pb_plan_pause_immediate_clicked
        )

        self._pb_plan_resume = QPushButton("Resume")
        self._pb_plan_resume.setEnabled(False)
        self._pb_plan_resume.clicked.connect(self._pb_plan_resume_clicked)

        self._pb_plan_stop = QPushButton("Stop")
        self._pb_plan_stop.setEnabled(False)
        self._pb_plan_stop.clicked.connect(self._pb_plan_stop_clicked)

        self._pb_plan_abort = QPushButton("Abort")
        self._pb_plan_abort.setEnabled(False)
        self._pb_plan_abort.clicked.connect(self._pb_plan_abort_clicked)

        self._pb_plan_halt = QPushButton("Halt")
        self._pb_plan_halt.setEnabled(False)
        self._pb_plan_halt.clicked.connect(self._pb_plan_halt_clicked)

        self._group_box = QGroupBox("Plan Execution")

        vbox = QVBoxLayout()
        hbox = QHBoxLayout()
        hbox.addWidget(self._pb_plan_pause_deferred)
        hbox.addWidget(self._pb_plan_pause_immediate)
        vbox.addLayout(hbox)
        vbox.addWidget(self._pb_plan_resume)
        hbox = QHBoxLayout()
        hbox.addWidget(self._pb_plan_stop)
        hbox.addWidget(self._pb_plan_abort)
        hbox.addWidget(self._pb_plan_halt)
        vbox.addLayout(hbox)
        self._group_box.setLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(self._group_box)
        self.setLayout(vbox)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widget.connect(self.slot_update_widgets)

    def on_update_widgets(self, event):
        is_connected = bool(event.is_connected)
        status = event.status
        self.signal_update_widget.emit(is_connected, status)

    @Slot(bool, object)
    def slot_update_widgets(self, is_connected, status):
        # 'is_connected' takes values True, False
        worker_exists = status.get("worker_environment_exists", False)
        manager_state = status.get("manager_state", None)
        self._pb_plan_pause_deferred.setEnabled(
            is_connected and worker_exists and (manager_state == "executing_queue")
        )
        self._pb_plan_pause_immediate.setEnabled(
            is_connected and worker_exists and (manager_state == "executing_queue")
        )
        self._pb_plan_resume.setEnabled(
            is_connected and worker_exists and (manager_state == "paused")
        )
        self._pb_plan_stop.setEnabled(
            is_connected and worker_exists and (manager_state == "paused")
        )
        self._pb_plan_abort.setEnabled(
            is_connected and worker_exists and (manager_state == "paused")
        )
        self._pb_plan_halt.setEnabled(
            is_connected and worker_exists and (manager_state == "paused")
        )

    def _pb_plan_pause_deferred_clicked(self):
        try:
            self.model.re_pause(option="deferred")
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_plan_pause_immediate_clicked(self):
        try:
            self.model.re_pause(option="immediate")
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_plan_resume_clicked(self):
        try:
            self.model.re_resume()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_plan_stop_clicked(self):
        try:
            self.model.re_stop()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_plan_abort_clicked(self):
        try:
            self.model.re_abort()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_plan_halt_clicked(self):
        try:
            self.model.re_halt()
        except Exception as ex:
            print(f"Exception: {ex}")


class QtReStatusMonitor(QWidget):
    signal_update_widget = Signal(object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._lb_environment_exists_text = "RE Environment: "
        self._lb_manager_state_text = "Manager state: "
        self._lb_re_state_text = "RE state: "
        self._lb_items_in_history_text = "Items in history: "
        self._lb_queue_is_running_text = "Queue is running: "
        self._lb_queue_stop_pending_text = "Queue STOP pending: "
        self._lb_items_in_queue_text = "Items in queue: "
        self._lb_queue_loop_mode_text = "Queue LOOP mode: "

        self._lb_environment_exists = QLabel(self._lb_environment_exists_text + "-")
        self._lb_manager_state = QLabel(self._lb_manager_state_text + "-")
        self._lb_re_state = QLabel(self._lb_re_state_text + "-")
        self._lb_items_in_history = QLabel(self._lb_items_in_history_text + "-")
        self._lb_queue_is_running = QLabel(self._lb_queue_is_running_text + "-")
        self._lb_queue_stop_pending = QLabel(self._lb_queue_stop_pending_text + "-")
        self._lb_items_in_queue = QLabel(self._lb_items_in_queue_text + "-")
        self._lb_queue_loop_mode = QLabel(self._lb_queue_loop_mode_text + "-")

        self._group_box = QGroupBox("RE Manager Status")

        hbox = QHBoxLayout()

        vbox = QVBoxLayout()
        vbox.addWidget(self._lb_environment_exists)
        vbox.addWidget(self._lb_manager_state)
        vbox.addWidget(self._lb_re_state)
        vbox.addWidget(self._lb_items_in_history)
        hbox.addLayout(vbox)

        hbox.addSpacing(10)

        vbox = QVBoxLayout()
        vbox.addWidget(self._lb_queue_is_running)
        vbox.addWidget(self._lb_queue_stop_pending)
        vbox.addWidget(self._lb_queue_loop_mode)
        vbox.addWidget(self._lb_items_in_queue)
        hbox.addLayout(vbox)

        self._group_box.setLayout(hbox)

        vbox = QVBoxLayout()
        vbox.addWidget(self._group_box)
        self.setLayout(vbox)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widget.connect(self.slot_update_widgets)

    def _set_label_text(self, label, prefix, value):
        if value is None:
            value = "-"
        label.setText(f"{prefix}{value}")

    def on_update_widgets(self, event):
        status = event.status
        self.signal_update_widget.emit(status)

    @Slot(object)
    def slot_update_widgets(self, status):
        worker_exists = status.get("worker_environment_exists", None)
        manager_state = status.get("manager_state", None)
        re_state = status.get("re_state", None)
        items_in_history = status.get("items_in_history", None)
        items_in_queue = status.get("items_in_queue", None)
        queue_is_running = bool(status.get("running_item_uid", False))
        queue_stop_pending = status.get("queue_stop_pending", None)

        queue_mode = status.get("plan_queue_mode", None)
        queue_loop_enabled = queue_mode.get("loop", None) if queue_mode else None

        # Capitalize state of RE Manager
        manager_state = (
            manager_state.upper() if isinstance(manager_state, str) else manager_state
        )
        re_state = re_state.upper() if isinstance(re_state, str) else re_state

        self._set_label_text(
            self._lb_environment_exists,
            self._lb_environment_exists_text,
            "OPEN" if worker_exists else "CLOSED",
        )
        self._set_label_text(
            self._lb_manager_state, self._lb_manager_state_text, manager_state
        )
        self._set_label_text(self._lb_re_state, self._lb_re_state_text, re_state)
        self._set_label_text(
            self._lb_items_in_history,
            self._lb_items_in_history_text,
            str(items_in_history),
        )
        self._set_label_text(
            self._lb_items_in_queue, self._lb_items_in_queue_text, str(items_in_queue)
        )
        self._set_label_text(
            self._lb_queue_is_running,
            self._lb_queue_is_running_text,
            "YES" if queue_is_running else "NO",
        )
        self._set_label_text(
            self._lb_queue_stop_pending,
            self._lb_queue_stop_pending_text,
            "YES" if queue_stop_pending else "NO",
        )

        self._set_label_text(
            self._lb_queue_loop_mode,
            self._lb_queue_loop_mode_text,
            "ON" if queue_loop_enabled else "OFF",
        )


class QueueTableWidget(QTableWidget):
    signal_drop_event = Signal(int, int)
    signal_scroll = Signal(str)
    signal_resized = Signal()

    def __init__(self):
        super().__init__()
        self._is_mouse_pressed = False
        self._is_scroll_active = False
        self._scroll_direction = ""

        self._scroll_timer_count = 0
        # Duration of period of the first series of events, ms
        self._scroll_timer_period_1 = 200
        # Duration of period of the remaining events, ms
        self._scroll_timer_period_2 = 100
        self._scroll_timer_n_events = 4  # The number of events in the first period
        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._on_scroll_timeout)

    def dropEvent(self, event):
        self.deactivate_scroll()
        row, col = -1, -1
        if (event.source() == self) and self.viewport().rect().contains(event.pos()):
            index = self.indexAt(event.pos())
            if not index.isValid() or not self.visualRect(index).contains(event.pos()):
                index = self.rootIndex()
            row = index.row()
            col = index.column()

        self.signal_drop_event.emit(row, col)

    def dragMoveEvent(self, event):
        # 'rowHeight(0)' will return 0 if the table is empty,
        #    but we don't need to scroll the empty table
        scroll_activation_area = int(self.rowHeight(0) / 2)

        y = event.pos().y()
        if y < scroll_activation_area:
            self.activate_scroll("up")
        elif y > self.viewport().height() - scroll_activation_area:
            self.activate_scroll("down")
        else:
            self.deactivate_scroll()

    def dragLeaveEvent(self, event):
        self.deactivate_scroll()

    def activate_scroll(self, str):
        if str not in ("up", "down"):
            return

        if not self._is_scroll_active or self._scroll_direction != str:
            self._is_scroll_active = True
            self._scroll_direction = str
            self._scroll_timer_count = 0
            # The period before the first scroll event should be very short
            self._scroll_timer.start(20)

    def deactivate_scroll(self):
        if self._is_scroll_active:
            self._is_scroll_active = False
            self._scroll_direction = ""
            self._scroll_timer.stop()

    def _on_scroll_timeout(self):
        self.signal_scroll.emit(self._scroll_direction)

        self._scroll_timer_count += 1
        timeout = (
            self._scroll_timer_period_1
            if self._scroll_timer_count <= self._scroll_timer_n_events
            else self._scroll_timer_period_2
        )
        self._scroll_timer.start(timeout)


class PushButtonMinimumWidth(QPushButton):
    """
    Push button minimum width necessary to fit the text
    """

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        text = self.text()
        font = self.font()

        fm = QFontMetrics(font)
        text_width = fm.width(text) + 6
        self.setFixedWidth(text_width)


class QtRePlanQueue(QWidget):

    signal_update_widgets = Signal(bool)
    signal_update_selection = Signal(str)
    signal_plan_queue_changed = Signal(object, str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._table_column_labels = (
            "",
            "Name",
            "Parameters",
            "USER",
            "GROUP",
        )
        self._table = QueueTableWidget()
        self._table.setColumnCount(len(self._table_column_labels))
        # self._table.verticalHeader().hide()
        self._table.setHorizontalHeaderLabels(self._table_column_labels)
        self._table.horizontalHeader().setSectionsMovable(True)

        self._table.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)

        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setDragEnabled(False)
        self._table.setAcceptDrops(False)
        self._table.setDropIndicatorShown(True)
        self._table.setShowGrid(True)

        self._table.setAlternatingRowColors(True)

        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setMinimumSectionSize(5)

        self._table_scrolled_to_bottom = False

        # The following parameters are used only to control widget state (e.g. activate/deactivate
        #   buttons), not to perform real operations.
        self._n_table_items = 0  # The number of items in the table
        self._n_selected_item = -1  # Selected item (table row)

        self._pb_move_up = PushButtonMinimumWidth("Move Up")
        self._pb_move_down = PushButtonMinimumWidth("Down")
        self._pb_move_to_top = PushButtonMinimumWidth("Top")
        self._pb_move_to_bottom = PushButtonMinimumWidth("Bottom")
        self._pb_delete_plan = PushButtonMinimumWidth("Delete")
        self._pb_duplicate_plan = PushButtonMinimumWidth("Duplicate")
        self._pb_clear_queue = PushButtonMinimumWidth("Clear")
        self._pb_deselect = PushButtonMinimumWidth("Deselect")
        self._pb_loop_on = PushButtonMinimumWidth("Loop")
        self._pb_loop_on.setCheckable(True)

        self._pb_move_up.clicked.connect(self._pb_move_up_clicked)
        self._pb_move_down.clicked.connect(self._pb_move_down_clicked)
        self._pb_move_to_top.clicked.connect(self._pb_move_to_top_clicked)
        self._pb_move_to_bottom.clicked.connect(self._pb_move_to_bottom_clicked)
        self._pb_delete_plan.clicked.connect(self._pb_delete_plan_clicked)
        self._pb_duplicate_plan.clicked.connect(self._pb_duplicate_plan_clicked)
        self._pb_clear_queue.clicked.connect(self._pb_clear_queue_clicked)
        self._pb_deselect.clicked.connect(self._pb_deselect_clicked)
        self._pb_loop_on.clicked.connect(self._pb_loop_on_clicked)

        self._group_box = QGroupBox("Plan Queue")
        vbox = QVBoxLayout()
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("QUEUE"))
        hbox.addStretch(1)
        hbox.addWidget(self._pb_move_up)
        hbox.addWidget(self._pb_move_down)
        hbox.addWidget(self._pb_move_to_top)
        hbox.addWidget(self._pb_move_to_bottom)
        hbox.addStretch(1)
        hbox.addWidget(self._pb_deselect)
        hbox.addWidget(self._pb_clear_queue)
        hbox.addStretch(1)
        hbox.addWidget(self._pb_loop_on)
        hbox.addStretch(1)
        hbox.addWidget(self._pb_delete_plan)
        hbox.addWidget(self._pb_duplicate_plan)
        vbox.addLayout(hbox)
        vbox.addWidget(self._table)
        self.setLayout(vbox)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widgets.connect(self.slot_update_widgets)

        self.model.events.plan_queue_changed.connect(self.on_plan_queue_changed)
        self.signal_plan_queue_changed.connect(self.slot_plan_queue_changed)

        self.model.events.queue_item_selection_changed.connect(
            self.on_queue_item_selection_changed
        )
        self.signal_update_selection.connect(self.slot_change_selection)

        self._table.signal_drop_event.connect(self.on_table_drop_event)
        self._table.signal_scroll.connect(self.on_table_scroll_event)

        self._table.itemSelectionChanged.connect(self.on_item_selection_changed)
        self._table.verticalScrollBar().valueChanged.connect(
            self.on_vertical_scrollbar_value_changed
        )
        self._table.verticalScrollBar().rangeChanged.connect(
            self.on_vertical_scrollbar_range_changed
        )

        self._update_button_states()

    def on_update_widgets(self, event):
        # None should be converted to False:
        is_connected = bool(event.is_connected)
        self.signal_update_widgets.emit(is_connected)

    @Slot(bool)
    def slot_update_widgets(self, is_connected):
        # Disable drops if there is no connection to RE Manager
        self._table.setDragEnabled(is_connected)
        self._table.setAcceptDrops(is_connected)

        self._update_button_states()

    def _update_button_states(self):
        is_connected = bool(self.model.re_manager_connected)
        status = self.model.re_manager_status
        loop_mode_on = status["plan_queue_mode"]["loop"] if status else False

        n_items = self._n_table_items
        n_selected_item = self._n_selected_item

        is_sel = n_selected_item >= 0
        sel_top = n_selected_item == 0
        sel_bottom = n_selected_item == n_items - 1

        self._pb_move_up.setEnabled(is_connected and is_sel and not sel_top)
        self._pb_move_down.setEnabled(is_connected and is_sel and not sel_bottom)
        self._pb_move_to_top.setEnabled(is_connected and is_sel and not sel_top)
        self._pb_move_to_bottom.setEnabled(is_connected and is_sel and not sel_bottom)

        self._pb_clear_queue.setEnabled(is_connected and n_items)
        self._pb_deselect.setEnabled(is_sel)

        self._pb_loop_on.setEnabled(is_connected)
        self._pb_loop_on.setChecked(loop_mode_on)

        self._pb_delete_plan.setEnabled(is_connected and is_sel)
        self._pb_duplicate_plan.setEnabled(is_connected and is_sel)

    def on_vertical_scrollbar_value_changed(self, value):
        max = self._table.verticalScrollBar().maximum()
        self._table_scrolled_to_bottom = value == max

    def on_vertical_scrollbar_range_changed(self, min, max):
        if self._table_scrolled_to_bottom:
            self._table.verticalScrollBar().setValue(max)

    def on_table_drop_event(self, row, col):
        # If the selected queue item is not in the table anymore (e.g. sent to execution),
        #   then ignore the drop event, since the item can not be moved.
        if self.model.selected_queue_item_uid:
            item_uid_to_replace = self.model.queue_item_pos_to_uid(row)
            try:
                self.model.queue_item_move_in_place_of(item_uid_to_replace)
            except Exception as ex:
                print(f"Exception: {ex}")

        self._update_button_states()

    def on_table_scroll_event(self, scroll_direction):
        v = self._table.verticalScrollBar().value()
        v_max = self._table.verticalScrollBar().maximum()
        if scroll_direction == "up" and v > 0:
            v_new = v - 1
        elif scroll_direction == "down" and v < v_max:
            v_new = v + 1
        else:
            v_new = v
        if v != v_new:
            self._table.verticalScrollBar().setValue(v_new)

    def on_plan_queue_changed(self, event):
        plan_queue_items = event.plan_queue_items
        selected_item_uid = event.selected_item_uid
        self.signal_plan_queue_changed.emit(plan_queue_items, selected_item_uid)

    @Slot(object, str)
    def slot_plan_queue_changed(self, plan_queue_items, selected_item_uid):

        # Check if the vertical scroll bar is scrolled to the bottom. Ignore the case
        #   when 'scroll_value==0': if the top plan is visible, it should remain visible
        #   even if additional plans are added to the queue.
        scroll_value = self._table.verticalScrollBar().value()
        scroll_maximum = self._table.verticalScrollBar().maximum()
        self._table_scrolled_to_bottom = scroll_value and (
            scroll_value == scroll_maximum
        )

        self._table.clearContents()
        self._table.setRowCount(len(plan_queue_items))

        if len(plan_queue_items):
            resize_mode = QHeaderView.ResizeToContents
        else:
            # Empty table, stretch the header
            resize_mode = QHeaderView.Stretch
        self._table.horizontalHeader().setSectionResizeMode(resize_mode)

        for nr, item in enumerate(plan_queue_items):
            for nc, col_name in enumerate(self._table_column_labels):
                try:
                    value = self.model.get_item_value_for_label(
                        item=item, label=col_name
                    )
                except KeyError:
                    value = ""
                table_item = QTableWidgetItem(value)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(nr, nc, table_item)

        # Update the number of table items
        self._n_table_items = len(plan_queue_items)

        # Advance scrollbar if the table is scrolled all the way down.
        if self._table_scrolled_to_bottom:
            scroll_maximum_new = self._table.verticalScrollBar().maximum()
            self._table.verticalScrollBar().setValue(scroll_maximum_new)

        self.slot_change_selection(selected_item_uid)
        self._update_button_states()

    def on_item_selection_changed(self):
        """
        The handler for ``item_selection_changed`` signal emitted by QTableWidget
        """
        sel_rows = self._table.selectionModel().selectedRows()
        # It is assumed that only one row may be selected at a time. If the table settings change
        #   so that more than one row could be selected at a time, the following code will not work.
        try:
            if len(sel_rows) >= 1:
                row = sel_rows[0].row()
                selected_item_uid = self.model.queue_item_pos_to_uid(row)
                self.model.selected_queue_item_uid = selected_item_uid
                self._n_selected_item = row
            else:
                raise Exception()
        except Exception:
            self.model.selected_queue_item_uid = ""
            self._n_selected_item = -1

    def on_queue_item_selection_changed(self, event):
        """
        The handler for the event generated by the model
        """
        selected_item_uid = event.selected_item_uid
        self.signal_update_selection.emit(selected_item_uid)

    @Slot(str)
    def slot_change_selection(self, selected_item_uid):
        row = -1
        if selected_item_uid:
            row = self.model.queue_item_uid_to_pos(selected_item_uid)
        if row < 0:
            self._table.clearSelection()
            self._n_selected_item = -1
        else:
            self._table.selectRow(row)
            self._n_selected_item = row

        self._update_button_states()

    def _pb_move_up_clicked(self):
        try:
            self.model.queue_item_move_up()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_move_down_clicked(self):
        try:
            self.model.queue_item_move_down()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_move_to_top_clicked(self):
        try:
            self.model.queue_item_move_to_top()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_move_to_bottom_clicked(self):
        try:
            self.model.queue_item_move_to_bottom()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_delete_plan_clicked(self):
        try:
            self.model.queue_item_remove()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_clear_queue_clicked(self):
        try:
            self.model.queue_clear()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_deselect_clicked(self):
        self._table.clearSelection()

    def _pb_loop_on_clicked(self):
        loop_enable = self._pb_loop_on.isChecked()
        try:
            self.model.queue_mode_loop_enable(loop_enable)
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_duplicate_plan_clicked(self):
        try:
            self.model.queue_item_copy_to_queue()
        except Exception as ex:
            print(f"Exception: {ex}")


class QtRePlanHistory(QWidget):
    signal_update_widgets = Signal()
    signal_update_selection = Signal(int)
    signal_plan_history_changed = Signal(object, int)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._table_column_labels = (
            "",
            "Name",
            "STATUS",
            "Parameters",
            "USER",
            "GROUP",
        )
        self._table = QueueTableWidget()
        self._table.setColumnCount(len(self._table_column_labels))
        # self._table.verticalHeader().hide()
        self._table.setHorizontalHeaderLabels(self._table_column_labels)
        self._table.horizontalHeader().setSectionsMovable(True)

        # self._table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)

        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(True)

        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setMinimumSectionSize(5)

        self._table_scrolled_to_bottom = False
        # self._table_slider_is_pressed = False

        # The following parameters are used only to control widget state (e.g. activate/deactivate
        #   buttons), not to perform real operations.
        self._n_table_items = 0  # The number of items in the table
        self._n_selected_item = -1  # Selected item (table row)

        self._pb_copy_to_queue = PushButtonMinimumWidth("Copy to Queue")
        self._pb_deselect_all = PushButtonMinimumWidth("Deselect All")
        self._pb_clear_history = PushButtonMinimumWidth("Clear History")

        self._pb_copy_to_queue.clicked.connect(self._pb_copy_to_queue_clicked)
        self._pb_deselect_all.clicked.connect(self._pb_deselect_all_clicked)
        self._pb_clear_history.clicked.connect(self._pb_clear_history_clicked)

        vbox = QVBoxLayout()
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("HISTORY"))
        hbox.addStretch(1)
        hbox.addWidget(self._pb_copy_to_queue)
        hbox.addStretch(3)
        hbox.addWidget(self._pb_deselect_all)
        hbox.addWidget(self._pb_clear_history)
        vbox.addLayout(hbox)
        vbox.addWidget(self._table)
        self.setLayout(vbox)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widgets.connect(self.slot_update_widgets)

        self.model.events.plan_history_changed.connect(self.on_plan_history_changed)
        self.signal_plan_history_changed.connect(self.slot_plan_history_changed)

        self.model.events.history_item_selection_changed.connect(
            self.on_history_item_selection_changed
        )
        self.signal_update_selection.connect(self.slot_change_selection)

        self._table.itemSelectionChanged.connect(self.on_item_selection_changed)
        self._table.verticalScrollBar().valueChanged.connect(
            self.on_vertical_scrollbar_value_changed
        )
        self._table.verticalScrollBar().rangeChanged.connect(
            self.on_vertical_scrollbar_range_changed
        )

        self._update_button_states()

    def on_vertical_scrollbar_value_changed(self, value):
        max = self._table.verticalScrollBar().maximum()
        self._table_scrolled_to_bottom = value == max

    def on_vertical_scrollbar_range_changed(self, min, max):
        if self._table_scrolled_to_bottom:
            self._table.verticalScrollBar().setValue(max)

    def on_update_widgets(self, event):
        self.signal_update_widgets.emit()

    @Slot()
    def slot_update_widgets(self):
        self._update_button_states()

    def _update_button_states(self):
        is_connected = bool(self.model.re_manager_connected)
        n_items = self._n_table_items
        n_selected_item = self._n_selected_item

        is_sel = n_selected_item >= 0

        self._pb_copy_to_queue.setEnabled(is_connected and is_sel)
        self._pb_deselect_all.setEnabled(is_sel)
        self._pb_clear_history.setEnabled(is_connected and n_items)

    def on_plan_history_changed(self, event):
        plan_history_items = event.plan_history_items
        selected_item_pos = event.selected_item_pos
        self.signal_plan_history_changed.emit(plan_history_items, selected_item_pos)

    @Slot(object, int)
    def slot_plan_history_changed(self, plan_history_items, selected_item_pos):
        # Check if the vertical scroll bar is scrolled to the bottom.
        scroll_value = self._table.verticalScrollBar().value()
        scroll_maximum = self._table.verticalScrollBar().maximum()
        self._table_scrolled_to_bottom = scroll_value == scroll_maximum

        self._table.clearContents()
        self._table.setRowCount(len(plan_history_items))

        if len(plan_history_items):
            resize_mode = QHeaderView.ResizeToContents
        else:
            # Empty table, stretch the header
            resize_mode = QHeaderView.Stretch
        self._table.horizontalHeader().setSectionResizeMode(resize_mode)

        for nr, item in enumerate(plan_history_items):
            for nc, col_name in enumerate(self._table_column_labels):
                try:
                    value = self.model.get_item_value_for_label(
                        item=item, label=col_name
                    )
                except KeyError:
                    value = ""
                table_item = QTableWidgetItem(value)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(nr, nc, table_item)

        # Update the number of table items
        self._n_table_items = len(plan_history_items)

        # Advance scrollbar if the table is scrolled all the way down.
        if self._table_scrolled_to_bottom:
            scroll_maximum_new = self._table.verticalScrollBar().maximum()
            self._table.verticalScrollBar().setValue(scroll_maximum_new)

        # Call function directly
        self.slot_change_selection(selected_item_pos)

        self._update_button_states()

    def on_item_selection_changed(self):
        """
        The handler for ``item_selection_changed`` signal emitted by QTableWidget
        """
        sel_rows = self._table.selectionModel().selectedRows()
        # It is assumed that only one row may be selected at a time. If the table settings change
        #   so that more than one row could be selected at a time, the following code will not work.
        try:
            if len(sel_rows) >= 1:
                selected_item_pos = sel_rows[0].row()
                self.model.selected_history_item_pos = selected_item_pos
                self._n_selected_item = selected_item_pos
            else:
                raise Exception()
        except Exception:
            self.model.selected_history_item_pos = -1
            self._n_selected_item = -1

    def on_history_item_selection_changed(self, event):
        """
        The handler for the event generated by the model
        """
        row = event.selected_item_pos
        self.signal_update_selection.emit(row)

    @Slot(int)
    def slot_change_selection(self, selected_item_pos):
        row = selected_item_pos

        if row < 0:
            self._table.clearSelection()
            self._n_selected_item = -1
        else:
            self._table.selectRow(row)
            self._n_selected_item = row

        self._update_button_states()

    def _pb_copy_to_queue_clicked(self):
        try:
            self.model.history_item_add_to_queue()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_deselect_all_clicked(self):
        self._table.clearSelection()
        self._n_selected_item = -1
        self._update_button_states()

    def _pb_clear_history_clicked(self):
        try:
            self.model.history_clear()
        except Exception as ex:
            print(f"Exception: {ex}")


class QtReRunningPlan(QWidget):
    signal_update_widgets = Signal()
    signal_running_item_changed = Signal(object, object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        # Set background color the same as for disabled window.
        p = self._text_edit.palette()
        p.setColor(QPalette.Base, p.color(QPalette.Disabled, QPalette.Base))
        self._text_edit.setPalette(p)

        self._pb_copy_to_queue = PushButtonMinimumWidth("Copy to Queue")

        self._pb_copy_to_queue.clicked.connect(self._pb_copy_to_queue_clicked)

        vbox = QVBoxLayout()
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("RUNNING PLAN"))
        hbox.addStretch(1)
        hbox.addWidget(self._pb_copy_to_queue)
        vbox.addLayout(hbox)
        vbox.addWidget(self._text_edit)
        self.setLayout(vbox)

        self._is_item_running = False
        self._running_item_uid = ""
        self._update_button_states()

        self.model.events.running_item_changed.connect(self.on_running_item_changed)
        self.signal_running_item_changed.connect(self.slot_running_item_changed)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widgets.connect(self.slot_update_widgets)

    def on_running_item_changed(self, event):
        running_item = event.running_item
        run_list = event.run_list
        self.signal_running_item_changed.emit(running_item, run_list)

    @Slot(object, object)
    def slot_running_item_changed(self, running_item, run_list):

        running_item_uid = running_item.get("item_uid", "")
        is_new_item = running_item_uid != self._running_item_uid
        self._running_item_uid = running_item_uid

        s_running_item = ""
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;"

        def _to_html(text, *, nindent=4):
            """Formats text as a sequence indented html lines. Lines are indented by `nindent` spaces"""
            lines = text.split("\n")
            lines_modified = []
            for line in lines:
                line_no_leading_spaces = line.lstrip(" ")
                n_leading_spaces = len(line) - len(line_no_leading_spaces)
                lines_modified.append(
                    "&nbsp;" * (n_leading_spaces + nindent) + line_no_leading_spaces
                )
            text_modified = "<br>".join(lines_modified)

            return text_modified

        if running_item:
            s_running_item += f"<b>Plan Name:</b> {running_item.get('name', '')}<br>"
            if ("args" in running_item) and running_item["args"]:
                s_running_item += (
                    f"<b>Arguments:</b> {str(running_item['args'])[1:-1]}<br>"
                )
            if ("kwargs" in running_item) and running_item["kwargs"]:
                s_running_item += "<b>Parameters:</b><br>"
                for k, v in running_item["kwargs"].items():
                    s_running_item += indent + f"<b>{k}:</b> {v}<br>"

            if ("meta" in running_item) and running_item["meta"]:
                # This representation of metadata may not be the best, but it is still reasonable.
                #   Note, that metadata may be a dictionary or a list of dictionaries.
                s_meta = pprint.pformat(running_item["meta"])
                s_meta = _to_html(s_meta)
                s_running_item += f"<b>Metadata:</b><br>{s_meta}<br>"

        s_run_list = "<b>Runs:</b><br>" if run_list else ""
        for run_info in run_list:
            run_uid = run_info["uid"]
            run_is_open = run_info["is_open"]
            run_exit_status = run_info["exit_status"]
            s_run = indent + f"{run_uid}  "
            if run_is_open:
                s_run += "In progress ..."
            else:
                s_run += f"Exit status: {run_exit_status}"
            s_run_list += s_run + "<br>"

        # The following logic is implemented:
        #   - always scroll to the top of the edit box when the new plan is started.
        #   - don't scroll if contents are changed during execution of a plan unless scroll bar
        #     is all the way down (contents may be changed e.g. during execution of multirun plans)
        #   - if the scroll bar is in the lowest position, then continue scrolling down as text
        #     is added (e.g. UIDs may be added to the list of Run UIDs as multirun plan is executed).
        scroll_value = 0 if is_new_item else self._text_edit.verticalScrollBar().value()
        scroll_maximum = self._text_edit.verticalScrollBar().maximum()
        tb_scrolled_to_bottom = scroll_value and (scroll_value == scroll_maximum)

        self._text_edit.setHtml(s_running_item + s_run_list)

        self._is_item_running = bool(running_item)
        self._update_button_states()

        scroll_maximum_new = self._text_edit.verticalScrollBar().maximum()
        scroll_value_new = scroll_maximum_new if tb_scrolled_to_bottom else scroll_value
        self._text_edit.verticalScrollBar().setValue(scroll_value_new)

    def on_update_widgets(self, event):
        self.signal_update_widgets.emit()

    @Slot()
    def slot_update_widgets(self):
        self._update_button_states()

    def _update_button_states(self):
        is_connected = bool(self.model.re_manager_connected)
        is_plan_running = self._is_item_running

        self._pb_copy_to_queue.setEnabled(is_connected and is_plan_running)

    def _pb_copy_to_queue_clicked(self):
        try:
            self.model.running_item_add_to_queue()
        except Exception as ex:
            print(f"Exception: {ex}")


# class FittedTextEdit(QTextEdit):
#     def __init__(self):
#         super().__init__()
#         self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
#         self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
#         self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
#
#     def sizeHint(self):
#       s = self.document().size().toSize()
#       print(f"width={s.width()} height={s.height()}")
#       return s
#
#     def resizeEvent(self, event):
#       self.updateGeometry()
#       super().resizeEvent(event)


class LineEditResized(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._hint_w = None

        p = self.palette()
        self._color_normal = p.color(QPalette.Normal, QPalette.Base)
        self._color_disabled = p.color(QPalette.Disabled, QPalette.Base)

    def setReadOnly(self, read_only):
        super().setReadOnly(read_only)
        p = self.palette()
        if read_only:
            p.setColor(QPalette.Base, self._color_disabled)
        else:
            p.setColor(QPalette.Base, self._color_normal)
        self.setPalette(p)

    def setTextAndResize(self, text, *, w_min=10, w_max=200, w_space=20):
        self.setText(text)

        fm = self.fontMetrics()
        width = fm.boundingRect(text).width() + w_space
        if w_max and (width > w_max):
            width = w_max
        if w_max < w_min:
            width = w_min
        self._hint_w = width

    def sizeHint(self):
        hint = super().sizeHint()
        if self._hint_w is not None:
            hint.setWidth(self._hint_w)
        return hint


class _QtRePlanEditorTable(QTableWidget):

    signal_parameters_valid = Signal(bool)
    signal_item_description_changed = Signal(str)

    def __init__(self, model, parent=None, *, editable=False, detailed=True):
        super().__init__(parent)
        self.model = model

        # Colors to display valid and invalid (based on validation) text entries in the table
        self._text_color_valid = QTableWidgetItem().foreground()
        self._text_color_invalid = QBrush(QColor(255, 0, 0))

        self._validation_disabled = False

        self._queue_item = None  # Copy of the displayed queue item
        self._params = []
        self._params_indices = []
        self._params_descriptions = {}

        self._item_meta = []
        self._item_result = []

        self._table_column_labels = ("Parameter", "", "Value")
        self.setColumnCount(len(self._table_column_labels))
        self.verticalHeader().hide()

        self.setHorizontalHeaderLabels(self._table_column_labels)

        self.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)

        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setShowGrid(True)

        self.setAlternatingRowColors(True)

        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setMinimumSectionSize(5)

        self.itemChanged.connect(self.table_item_changed)

        self._editable = editable  # Table is editable
        self._detailed = (
            detailed  # Detailed view of parameters (show all plan parameters)
        )
        self.show_item(item=None)

    @property
    def editable(self):
        return self._editable

    @editable.setter
    def editable(self, is_editable):
        if self._editable != is_editable:
            self._editable = bool(is_editable)
            self._fill_table()

    @property
    def detailed(self):
        return self._detailed

    @detailed.setter
    def detailed(self, is_detailed):
        if self._detailed != is_detailed:
            self._detailed = bool(is_detailed)
            self._fill_table()

    @property
    def queue_item(self):
        """
        Returns original queue item.
        """
        return self._queue_item

    def get_modified_item(self):
        """
        Returns queue item that was modified during editing.
        """
        return self._params_to_item(self._params, self._queue_item)

    def _clear_table(self):
        self._params = []
        self._params_indices = []
        self.clearContents()
        self.setRowCount(0)

    def _item_to_params(self, item):

        if item is None:
            return [], {}, [], []

        # Get plan parameters (probably should be a function call)
        item_name = item.get("name", None)
        item_type = item.get("item_type", None)
        if item_type in ("plan", "instruction"):
            if item_type == "plan":
                item_params = self.model.get_allowed_plan_parameters(name=item_name)
            else:
                item_params = self.model.get_allowed_instruction_parameters(
                    name=item_name
                )
            item_editable = (item_name is not None) and (item_params is not None)
            params_descriptions = self.model.extract_descriptions_from_item_parameters(
                item_parameters=item_params
            )
            params_descriptions = self.model.format_item_parameter_descriptions(
                item_descriptions=params_descriptions
            )
        else:
            raise RuntimeError(f"Unknown item type '{item_type}'")

        item_args, item_kwargs = self.model.get_bound_item_arguments(item)
        if item_args:
            # Failed to bound the arguments. It is likely that the plan can not be submitted
            #   so consider it not editable. Display 'args' as a separate parameter named 'ARGS'.
            item_editable = False
            item_kwargs = dict(**{"ARGS": item_args}, **item_kwargs)

        # print(f"plan_params={pprint.pformat(plan_params)}")
        if item_editable:
            # Construct parameters (list of inspect.Parameter objects)
            parameters, created_type_list = _construct_parameters(
                item_params.get("parameters", {})
            )
            # print(f"parameters = {parameters}")
            # print(f"default = {[_.default for _ in parameters]}")
        else:
            parameters = []
            for key, val in item_kwargs.items():
                p = inspect.Parameter(
                    key,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=inspect.Parameter.empty,
                    annotation=inspect.Parameter.empty,
                )
                parameters.append(p)

        params = []
        for p in parameters:
            param_value = (
                item_kwargs[p.name]
                if (p.name in item_kwargs)
                else inspect.Parameter.empty
            )
            is_value_set = (param_value != inspect.Parameter.empty) or (
                p.default == inspect.Parameter.empty
                and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
            )

            # description = item_descriptions.get("parameters", {}).get(p.name, None)
            # if not description:
            #     description = f"Description for parameter {p.name} was not found ..."
            params.append(
                {
                    "name": p.name,
                    "value": param_value,
                    "is_value_set": is_value_set,
                    "parameters": p,
                }
            )

        # If metadata exists, it will be displayed after the plan parameters
        meta, item_meta = item.get("meta", {}), []
        if meta:
            if isinstance(meta, list):
                for n, key in enumerate(meta):
                    item_meta.append((f"METADATA {n}", ""))
                    for k, v in key.items():
                        item_meta.append((k, str(v)))
            else:
                item_meta.append(("METADATA", ""))
                for k, v in meta.items():
                    item_meta.append((f"- {k}", str(v)))

        # If results of plan execution exist, they will be displayed after the plan parameters
        result, item_result = item.get("result", {}), []
        if result:
            item_result.append(("RESULT", ""))
            for k, v in result.items():
                item_result.append((f"- {k}", str(v)))

        return params, params_descriptions, item_meta, item_result

    def _params_to_item(self, params, item):
        item = copy.deepcopy(item)

        # Find if there are VAR_POSITIONAL or VAR_KEYWORD arguments with set values
        n_var_pos, n_var_kwd = -1, -1
        for n, p in enumerate(params):
            if p["is_value_set"] and (p["value"] != inspect.Parameter.empty):
                if p["parameters"].kind == inspect.Parameter.VAR_POSITIONAL:
                    n_var_pos = n
                elif p["parameters"].kind == inspect.Parameter.VAR_KEYWORD:
                    n_var_kwd = n

        # Collect 'args'
        args = []
        if n_var_pos > 0:
            if not isinstance(params[n_var_pos]["value"], (list, tuple)):
                raise ValueError(
                    f"Invalid type of VAR_POSITIONAL argument: {params[n_var_pos]['value']}"
                )
            for n in range(n_var_pos):
                if params[n]["is_value_set"] and (
                    params[n]["value"] != inspect.Parameter.empty
                ):
                    args.append(params[n]["value"])
            args.extend(params[n_var_pos]["value"])

        # Collect 'kwargs'
        n_start = 0 if n_var_pos < 0 else n_var_pos + 1
        n_stop = len(params) if n_var_kwd < 0 else n_var_kwd

        kwargs = {}
        for n in range(n_start, n_stop):
            if params[n]["is_value_set"] and (
                params[n]["value"] != inspect.Parameter.empty
            ):
                kwargs[params[n]["parameters"].name] = params[n]["value"]

        if n_var_kwd > 0:
            if not isinstance(params[n_var_kwd]["value"], dict):
                raise ValueError(
                    f"Invalid type of VAR_KEYWORD argument: {params[n_var_kwd]['value']}"
                )
            kwargs.update(params[n_var_kwd]["value"])

        item["args"] = args
        item["kwargs"] = kwargs

        return item

    def _show_row_value(self, *, row):
        def print_value(v):
            if isinstance(v, str):
                return f"'{v}'"
            else:
                return str(v)

        p = self._params[row]
        p_name = p["name"]
        value = p["value"]
        default_value = p["parameters"].default
        is_var_positional = p["parameters"].kind == inspect.Parameter.VAR_POSITIONAL
        is_var_keyword = p["parameters"].kind == inspect.Parameter.VAR_KEYWORD
        is_value_set = p["is_value_set"]
        is_optional = (
            (default_value != inspect.Parameter.empty)
            or is_var_positional
            or is_var_keyword
        )
        is_editable = self._editable and (is_value_set or not is_optional)

        description = self._params_descriptions.get("parameters", {}).get(p_name, None)
        if not description:
            description = f"Description for parameter '{p_name}' was not found ..."

        v = value if is_value_set else default_value
        s_value = "" if v == inspect.Parameter.empty else print_value(v)
        if not is_value_set and s_value:
            s_value += " (default)"

        # Set checkable item in column 1
        check_item = QTableWidgetItem()
        check_item.setFlags(check_item.flags() | Qt.ItemIsUserCheckable)
        if not is_optional:
            # Checked and disabled
            check_item.setFlags(check_item.flags() & ~Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Checked)
        else:
            if self._editable:
                check_item.setFlags(check_item.flags() | Qt.ItemIsEnabled)
            else:
                check_item.setFlags(check_item.flags() & ~Qt.ItemIsEnabled)

            if is_value_set:
                check_item.setCheckState(Qt.Checked)
            else:
                check_item.setCheckState(Qt.Unchecked)

        self.setItem(row, 1, check_item)

        # Set value in column 2
        value_item = QTableWidgetItem(s_value)

        if is_editable:
            value_item.setFlags(value_item.flags() | Qt.ItemIsEditable)
        else:
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)

        if is_value_set:
            value_item.setFlags(value_item.flags() | Qt.ItemIsEnabled)
        else:
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEnabled)

        value_item.setToolTip(description)

        self.setItem(row, 2, value_item)

    def _fill_table(self):
        def print_value(v):
            if isinstance(v, str):
                return f"'{v}'"
            else:
                return str(v)

        self._validation_disabled = True
        self.clearContents()

        params = self._params
        params_descriptions = self._params_descriptions
        item_meta = self._item_meta
        item_result = self._item_result

        # By default select all indexes of 'params'
        self._params_indices = list(range(len(params)))
        params_indices = self._params_indices

        # Remove parameters with default values (only when editing is disabled)
        if (not self._editable) and (not self._detailed):
            params_indices.clear()
            for n, p in enumerate(params):
                if p["value"] != inspect.Parameter.empty:
                    params_indices.append(n)

        self.setRowCount(len(params_indices) + len(item_meta) + len(item_result))

        for n, p_index in enumerate(params_indices):
            p = params[p_index]

            is_var_positional = p["parameters"].kind == inspect.Parameter.VAR_POSITIONAL
            is_var_keyword = p["parameters"].kind == inspect.Parameter.VAR_KEYWORD

            key = p["parameters"].name
            value = p["value"]
            default_value = p["parameters"].default

            description = params_descriptions.get("parameters", {}).get(key, None)
            if not description:
                description = (
                    f"Description for parameter '{self._queue_item.get('name', '-')}' "
                    f"was not found ..."
                )

            is_value_set = p["is_value_set"]

            v = value if is_value_set else default_value
            s_value = "" if v == inspect.Parameter.empty else print_value(v)
            if not is_value_set:
                s_value += " (default)"

            key_name = str(key)
            if is_var_positional:
                key_name = f"*{key_name}"
            elif is_var_keyword:
                key_name = f"**{key_name}"
            key_item = QTableWidgetItem(key_name)
            key_item.setToolTip(description)
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            self.setItem(n, 0, key_item)

            self._show_row_value(row=n)

        # Display metadata (if exists)
        n_row = len(params_indices)  # Number of table row
        for k, v in item_meta:
            key_item = QTableWidgetItem(str(k))
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            self.setItem(n_row, 0, key_item)
            value_item = QTableWidgetItem(str(v))
            value_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            self.setItem(n_row, 2, value_item)
            n_row += 1

        # Display results (if exist)
        for k, v in item_result:
            key_item = QTableWidgetItem(str(k))
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            self.setItem(n_row, 0, key_item)
            value_item = QTableWidgetItem(str(v))
            value_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            self.setItem(n_row, 2, value_item)
            n_row += 1

        self._validation_disabled = False
        self._validate_cell_values()

    def show_item(self, *, item, editable=None):
        if editable is not None:
            self._editable = bool(editable)

        # Keep the copy of the queue item
        self._queue_item = copy.deepcopy(item)
        self.reset_item()

    def reset_item(self):
        # Generate parameters
        (
            self._params,
            self._params_descriptions,
            self._item_meta,
            self._item_result,
        ) = self._item_to_params(self._queue_item)
        if not self._queue_item:
            self._clear_table()
            description = ""
        else:
            self._fill_table()

            description = self._params_descriptions.get("description", "")
            if not description:
                name = self._queue_item.get("name", "-")
                description = f"Description for the item '{name}' was not found ..."

        # Send the signal that updates item description somewhere else in the code
        self.signal_item_description_changed.emit(description)

    def _validate_cell_values(self):
        """
        Validates each cell in the table that is expected to have manually entered parameters.
        Skips the cells that display the default parameters.

        The function also saves successfully evaluated values to the parameter list.

        Signal is emitted to report results of parameter validation (may be used to
        enable/disable buttons in other widges, e.g. 'Ok' button).
        """
        # Validation may be disabled while the table is being filled.
        if self._validation_disabled:
            return

        data_valid = True
        for n, p_index in enumerate(self._params_indices):
            p = self._params[p_index]
            if p["is_value_set"]:
                table_item = self.item(n, 2)

                if table_item:
                    cell_valid = True
                    cell_text = table_item.text()
                    try:
                        # Currently the simples verification is performed:
                        #   - The cell is evaluated.
                        #   - If the evaluation is successful, then the value is saved.
                        # TODO: verify type of the loaded value whenever possible
                        p["value"] = ast.literal_eval(cell_text)
                    except Exception:
                        cell_valid = False
                        data_valid = False

                    table_item.setForeground(
                        self._text_color_valid
                        if cell_valid
                        else self._text_color_invalid
                    )

        self.signal_parameters_valid.emit(data_valid)

    def table_item_changed(self, table_item):
        try:
            row = self.row(table_item)
            column = self.column(table_item)
            if column == 1:
                is_checked = table_item.checkState() == Qt.Checked
                if self._params[row]["is_value_set"] != is_checked:

                    if (
                        is_checked
                        and self._params[row]["value"] == inspect.Parameter.empty
                    ):
                        self._params[row]["value"] = self._params[row][
                            "parameters"
                        ].default

                    self._params[row]["is_value_set"] = is_checked
                    self._show_row_value(row=row)

            elif column == 2:
                self._validate_cell_values()
        except ValueError:
            pass


class _QtReViewer(QWidget):

    signal_update_widgets = Signal()
    signal_update_selection = Signal(int)
    signal_edit_queue_item = Signal(object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._queue_item_name = ""
        self._queue_item_type = None

        self._lb_item_type = QLabel("Plan:")
        self._lb_item_name_default = "-"
        self._lb_item_name = QLabel(self._lb_item_name_default)
        self._cb_show_optional = QCheckBox("All Parameters")
        self._lb_item_source = QLabel("QUEUE ITEM")

        self._pb_copy_to_queue = QPushButton("Copy to Queue")
        self._pb_edit = QPushButton("Edit")

        # Start with 'detailed' view (show optional parameters)
        self._wd_editor = _QtRePlanEditorTable(
            self.model, editable=False, detailed=True
        )
        self._cb_show_optional.setChecked(
            Qt.Checked if self._wd_editor.detailed else Qt.Unchecked
        )

        vbox = QVBoxLayout()
        hbox = QHBoxLayout()
        hbox.addWidget(self._lb_item_type)
        hbox.addWidget(self._lb_item_name)
        hbox.addStretch(5)
        hbox.addWidget(self._cb_show_optional)
        hbox.addStretch(1)
        hbox.addWidget(self._lb_item_source)
        vbox.addLayout(hbox)

        vbox.addWidget(self._wd_editor)

        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(self._pb_copy_to_queue)
        hbox.addWidget(self._pb_edit)
        vbox.addLayout(hbox)

        self.setLayout(vbox)

        self._cb_show_optional.stateChanged.connect(
            self._cb_show_optional_state_changed
        )
        self._pb_copy_to_queue.clicked.connect(self._pb_copy_to_queue_clicked)
        self._pb_edit.clicked.connect(self._pb_edit_clicked)

        self.model.events.queue_item_selection_changed.connect(
            self.on_queue_item_selection_changed
        )
        self.signal_update_selection.connect(self.slot_change_selection)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widgets.connect(self.slot_update_widgets)

        self._wd_editor.signal_item_description_changed.connect(
            self.slot_item_description_changed
        )

    def on_queue_item_selection_changed(self, event):
        sel_item_uid = event.selected_item_uid
        sel_item_pos = self.model.queue_item_uid_to_pos(sel_item_uid)
        self.signal_update_selection.emit(sel_item_pos)

    def on_update_widgets(self, event):
        self.signal_update_widgets.emit()

    @Slot()
    def slot_update_widgets(self):
        self._update_widget_state()

    def _update_widget_state(self):
        item_name = self._queue_item_name
        item_type = self._queue_item_type

        if item_type == "plan":
            is_item_allowed = (
                self.model.get_allowed_plan_parameters(name=item_name) is not None
            )
        elif item_type == "instruction":
            is_item_allowed = (
                self.model.get_allowed_instruction_parameters(name=item_name)
                is not None
            )
        else:
            is_item_allowed = False

        is_connected = bool(self.model.re_manager_connected)

        self._pb_copy_to_queue.setEnabled(is_item_allowed and is_connected)
        self._pb_edit.setEnabled(is_item_allowed)

    @Slot(str)
    def slot_item_description_changed(self, item_description):
        self._lb_item_name.setToolTip(item_description)

    @Slot(int)
    def slot_change_selection(self, sel_item_pos):
        if sel_item_pos >= 0:
            item = copy.deepcopy(self.model._plan_queue_items[sel_item_pos])
        else:
            item = None

        default_name = self._lb_item_name_default
        self._queue_item_name = item.get("name", default_name) if item else default_name
        self._queue_item_type = item.get("item_type", None) if item else None

        # Displayed item type is supposed to be 'Instruction:' if an instruction is selected,
        #   otherwise it should be 'Plan:' (even if nothing is selected)
        displayed_item_type = (
            "Instruction:" if self._queue_item_type == "instruction" else "Plan:"
        )
        self._lb_item_type.setText(displayed_item_type)

        self._lb_item_name.setText(self._queue_item_name)

        self._update_widget_state()
        self._wd_editor.show_item(item=item)

    def _cb_show_optional_state_changed(self, state):
        is_checked = state == Qt.Checked
        self._wd_editor.detailed = is_checked

    def _pb_copy_to_queue_clicked(self):
        """
        Copy currently selected item to queue.
        """
        try:
            self.model.queue_item_copy_to_queue()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_edit_clicked(self):
        sel_item_uid = self.model.selected_queue_item_uid
        sel_item = self.model.queue_item_by_uid(sel_item_uid)  # Returns deep copy
        self.signal_edit_queue_item.emit(sel_item)


class _QtReEditor(QWidget):

    signal_update_widgets = Signal()
    signal_switch_tab = Signal(str)
    signal_allowed_plan_changed = Signal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._queue_item_type = None  # ???
        self._queue_item_name = None  # ???

        self._current_item_type = "plan"
        self._current_plan_name = ""
        self._current_instruction_name = ""
        self._current_item_source = ""  # Values: "", "NEW ITEM", "QUEUE ITEM"

        self._queue_item_loaded = False
        self._editor_state_valid = False

        self._rb_item_plan = QRadioButton("Plan")
        self._rb_item_plan.setChecked(True)
        self._rb_item_instruction = QRadioButton("Instruction")
        self._grp_item_type = QButtonGroup()
        self._grp_item_type.addButton(self._rb_item_plan)
        self._grp_item_type.addButton(self._rb_item_instruction)

        self._combo_item_list = QComboBox()
        self._combo_item_list.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        # self._combo_item_list.setSizePolicy(QComboBox.AdjustToContents)
        self._combo_item_list.currentIndexChanged.connect(
            self._combo_item_list_sel_changed
        )

        self._pb_new_item = QPushButton("New")
        self._lb_item_source = QLabel(self._current_item_source)

        # Start with 'detailed' view (show optional parameters)
        self._wd_editor = _QtRePlanEditorTable(
            self.model, editable=False, detailed=True
        )
        self._wd_editor.signal_parameters_valid.connect(self._slot_parameters_valid)
        self._wd_editor.signal_item_description_changed.connect(
            self._slot_item_description_changed
        )

        self._pb_add_to_queue = QPushButton("Add to Queue")
        self._pb_save_item = QPushButton("Save")
        self._pb_reset = QPushButton("Reset")
        self._pb_cancel = QPushButton("Cancel")

        self._pb_new_item.clicked.connect(self._pb_new_item_clicked)
        self._pb_add_to_queue.clicked.connect(self._pb_add_to_queue_clicked)
        self._pb_save_item.clicked.connect(self._pb_save_item_clicked)
        self._pb_reset.clicked.connect(self._pb_reset_clicked)
        self._pb_cancel.clicked.connect(self._pb_cancel_clicked)

        self._grp_item_type.buttonToggled.connect(self._grp_item_type_button_toggled)

        vbox = QVBoxLayout()
        hbox = QHBoxLayout()
        hbox.addWidget(self._rb_item_plan)
        hbox.addWidget(self._rb_item_instruction)
        hbox.addWidget(self._combo_item_list)
        hbox.addStretch(1)
        hbox.addWidget(self._pb_new_item)
        hbox.addWidget(self._lb_item_source)
        vbox.addLayout(hbox)

        vbox.addWidget(self._wd_editor)

        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(self._pb_add_to_queue)
        hbox.addWidget(self._pb_save_item)
        hbox.addWidget(self._pb_reset)
        hbox.addWidget(self._pb_cancel)
        vbox.addLayout(hbox)

        self.setLayout(vbox)

        self.model.events.allowed_plans_changed.connect(self._on_allowed_plans_changed)
        self.signal_allowed_plan_changed.connect(self._slot_allowed_plans_changed)

        self.model.events.status_changed.connect(self.on_update_widgets)
        self.signal_update_widgets.connect(self.slot_update_widgets)

        self._set_allowed_item_list()

        self._update_widget_state()

    def _set_allowed_item_list(self):
        # self._queue_item_type must be "plan" or "instruction"
        # self._current_plan_name and self._current_item_name should be properly set.
        #   The first item in the list is selected if the value is set to "".
        #   No element selected if the element with the given name is not in the list.

        if self._current_item_type == "plan":
            allowed_item_names = self.model.get_allowed_plan_names()
            if (not self._current_plan_name) and (allowed_item_names):
                self._current_plan_name = allowed_item_names[0]
            item_name = self._current_plan_name

        elif self._current_item_type == "instruction":
            allowed_item_names = self.model.get_allowed_instruction_names()
            if (not self._current_instruction_name) and (allowed_item_names):
                self._current_instruction_name = allowed_item_names[0]
            item_name = self._current_instruction_name

        self._combo_item_list.clear()
        self._combo_item_list.addItems(allowed_item_names)

        try:
            index = allowed_item_names.index(item_name)
        except ValueError:
            index = -1

        self._combo_item_list.setCurrentIndex(index)

    def _update_widget_state(self):

        is_connected = bool(self.model.re_manager_connected)

        self._rb_item_plan.setEnabled(not self._queue_item_loaded)
        self._rb_item_instruction.setEnabled(not self._queue_item_loaded)
        self._combo_item_list.setEnabled(not self._queue_item_loaded)
        self._pb_new_item.setEnabled(not self._queue_item_loaded)
        self._pb_new_item.setVisible(not self._queue_item_loaded)

        self._pb_add_to_queue.setEnabled(self._editor_state_valid and is_connected)
        self._pb_save_item.setEnabled(
            self._editor_state_valid
            and is_connected
            and self._current_item_source == "QUEUE ITEM"
        )
        self._pb_reset.setEnabled(self._queue_item_loaded)
        self._pb_cancel.setEnabled(self._queue_item_loaded)

        self._lb_item_source.setText(self._current_item_source)

    def edit_queue_item(self, queue_item):
        self._current_item_source = "QUEUE ITEM"
        self._edit_item(queue_item)

    def _edit_item(self, queue_item):
        self._queue_item_name = queue_item.get("name", None)
        self._queue_item_type = queue_item.get("item_type", None)

        if (
            self._queue_item_name
            and self._queue_item_type
            and self._queue_item_type in ("plan", "instruction")
        ):

            if self._queue_item_type == "instruction":
                self._current_instruction_name = self._queue_item_name
                self._rb_item_instruction.setChecked(True)
            else:
                self._current_plan_name = self._queue_item_name
                self._rb_item_plan.setChecked(True)

            self._set_allowed_item_list()

            self._wd_editor.show_item(item=queue_item, editable=True)

            self._queue_item_loaded = True
            self._update_widget_state()

    def _show_item_preview(self):
        """
        Generate and display preview (not editable)
        """
        item_name = self._combo_item_list.currentText()
        item_type = self._current_item_type
        if item_name:
            item = {"item_type": item_type, "name": item_name}
            self._wd_editor.show_item(item=item, editable=False)

    def _save_selected_item_name(self):
        item_name = self._combo_item_list.currentText()
        item_type = self._current_item_type
        if item_name:
            if item_type == "plan":
                self._current_plan_name = item_name
            elif item_type == "instruction":
                self._current_instruction_name = item_name

    def on_update_widgets(self, event):
        self.signal_update_widgets.emit()

    @Slot()
    def slot_update_widgets(self):
        self._update_widget_state()

    @Slot(str)
    def _slot_item_description_changed(self, item_description):
        self._combo_item_list.setToolTip(item_description)

    @Slot(bool)
    def _slot_parameters_valid(self, is_valid):
        self._editor_state_valid = is_valid
        self._update_widget_state()

    def _pb_new_item_clicked(self):
        item_type = self._current_item_type
        item_name = self._combo_item_list.currentText()
        if item_name:
            new_item = {"item_type": item_type, "name": item_name}
            self._current_item_source = "NEW ITEM"
            self._edit_item(new_item)

    def _pb_add_to_queue_clicked(self):
        """
        Add item to queue
        """
        item = self._wd_editor.get_modified_item()
        try:
            self.model.queue_item_add(item=item)
            self._wd_editor.show_item(item=None)
            self.signal_switch_tab.emit("view")
            self._queue_item_loaded = False
            self._current_item_source = ""
            self._update_widget_state()
            self._show_item_preview()

        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_save_item_clicked(self):
        """
        Save item to queue (update the edited item)
        """
        item = self._wd_editor.get_modified_item()
        try:
            self.model.queue_item_update(item=item)
            self._wd_editor.show_item(item=None)
            self.signal_switch_tab.emit("view")
            self._queue_item_loaded = False
            self._current_item_source = ""
            self._update_widget_state()
            self._show_item_preview()
        except Exception as ex:
            print(f"Exception: {ex}")

    def _pb_reset_clicked(self):
        """
        Restore parameters to the original values
        """
        self._wd_editor.reset_item()

    def _pb_cancel_clicked(self):
        self._wd_editor.show_item(item=None)
        self._queue_item_loaded = False
        self._queue_item_type = ""
        self._queue_item_name = ""
        self._current_item_source = ""
        self._update_widget_state()
        self._show_item_preview()

    def _grp_item_type_button_toggled(self, button, checked):
        if checked:
            if button == self._rb_item_plan:
                self._current_item_type = "plan"
                self._set_allowed_item_list()
            elif button == self._rb_item_instruction:
                self._current_item_type = "instruction"
                self._set_allowed_item_list()

    def _combo_item_list_sel_changed(self, index):
        self._save_selected_item_name()
        # We don't process the case when the list of allowed plans changes and the selected
        #   item is not in the list. But this is not a practical case.
        if not self._queue_item_loaded:
            self._show_item_preview()

    def _on_allowed_plans_changed(self, allowed_plans):
        self.signal_allowed_plan_changed.emit()

    @Slot()
    def _slot_allowed_plans_changed(self):
        self._set_allowed_item_list()


class QtRePlanEditor(QWidget):
    signal_update_widgets = Signal()
    signal_running_item_changed = Signal(object, object)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self._plan_viewer = _QtReViewer(model)
        self._plan_editor = _QtReEditor(model)

        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._plan_viewer, "Plan Viewer")
        self._tab_widget.addTab(self._plan_editor, "Plan Editor")

        vbox = QVBoxLayout()
        vbox.addWidget(self._tab_widget)
        self.setLayout(vbox)

        self._plan_viewer.signal_edit_queue_item.connect(self._edit_queue_item)
        self._plan_editor.signal_switch_tab.connect(self._switch_tab)

    @Slot(str)
    def _switch_tab(self, tab):
        tabs = {"view": self._plan_viewer, "edit": self._plan_editor}
        self._tab_widget.setCurrentWidget(tabs[tab])

    @Slot(object)
    def _edit_queue_item(self, queue_item):
        self._switch_tab("edit")
        self._plan_editor.edit_queue_item(queue_item)
