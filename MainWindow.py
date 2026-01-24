import os
import shutil
import tempfile

from AudioPlayerBackend import AudioPlayerBackend
from WaveformData import load_waveform
from Scrambler import AudioScrambler

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QSlider
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QMouseEvent


class WaveformWidget(QWidget):
    """
    Waveform display for the entire audio file.
    Expects a list of samples in [-1.0, 1.0].
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setAutoFillBackground(True)
        self.samples = []  # list[float] in [-1.0, 1.0]

    def set_samples(self, samples):
        """Set the waveform samples and repaint."""
        self.samples = samples or []
        self.update()

    def paintEvent(self, event):
        rect = self.rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # background
        painter.fillRect(rect, QColor(20, 20, 30))
        mid_y = rect.center().y()

        # center axis
        axis_pen = QPen(QColor(80, 80, 100))
        axis_pen.setWidth(1)
        painter.setPen(axis_pen)
        painter.drawLine(rect.left(), mid_y, rect.right(), mid_y)

        #no samples/audio
        if not self.samples:
            painter.end()
            return

        # waveform pen
        pen = QPen(QColor(0, 200, 150))
        pen.setWidth(1)
        painter.setPen(pen)

        width = rect.width()
        height = rect.height()
        if width <= 1 or height <= 1:
            painter.end()
            return

        amplitude = height * 0.45
        num_samples = len(self.samples)

        # vertical min/max bar per x
        for x in range(width):
            start_idx = int(x * num_samples / width)
            end_idx = int((x + 1) * num_samples / width)
            if end_idx <= start_idx:
                end_idx = start_idx + 1
            if end_idx > num_samples:
                end_idx = num_samples

            segment = self.samples[start_idx:end_idx]
            if not segment:
                continue

            seg_min = min(segment)
            seg_max = max(segment)

            y_min = int(mid_y - seg_max * amplitude)
            y_max = int(mid_y - seg_min * amplitude)

            painter.drawLine(x, y_min, x, y_max)

        painter.end()


class ClickableSlider(QSlider):
    """
    QSlider that jumps to the clicked position on the groove.
    """

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.orientation() == Qt.Horizontal:
                if hasattr(event, "position"):
                    x = event.position().x()
                else:
                    x = event.pos().x()

                width = max(1, self.width())
                ratio = x / width
                ratio = max(0.0, min(1.0, ratio))
                new_val = self.minimum() + int(ratio * (self.maximum() - self.minimum()))
                self.setValue(new_val)

        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Scrambler")

        # ---------- Scrambler ----------
        self.scrambler = AudioScrambler(block_ms=50, seed=12345)

        # ---------- INPUT (TOP) BACKEND ----------
        self.current_file_in = None
        self.is_paused_in = False
        self.playback_state_in = "stopped"  # "stopped" | "playing" | "paused"

        self.audio_player_in = AudioPlayerBackend(self)
        self.track_duration_ms_in = 0
        self.slider_is_pressed_in = False

        self.audio_player_in.position_changed.connect(self.on_player_position_changed_in)
        self.audio_player_in.duration_changed.connect(self.on_player_duration_changed_in)

        # ---------- OUTPUT (BOTTOM) BACKEND ----------
        self.current_file_out = None
        self.is_paused_out = False
        self.playback_state_out = "stopped"
        self.is_out_scrambled = False  # tracks whether bottom audio is scrambled

        self.audio_player_out = AudioPlayerBackend(self)
        self.track_duration_ms_out = 0
        self.slider_is_pressed_out = False

        self.audio_player_out.position_changed.connect(self.on_player_position_changed_out)
        self.audio_player_out.duration_changed.connect(self.on_player_duration_changed_out)

        # Temporary files for scrambled / unscrambled
        self.scrambled_temp_path = os.path.join(
            tempfile.gettempdir(), "audio_scrambler_scrambled.wav"
        )
        self.unscrambled_temp_path = os.path.join(
            tempfile.gettempdir(), "audio_scrambler_unscrambled.wav"
        )

        # ---------- MAIN LAYOUT ----------
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout()
        central.setLayout(main_layout)

        # ========== TOP SECTION (INPUT ORIGINAL) ==========
        top_section = QWidget()
        top_layout = QVBoxLayout()
        top_section.setLayout(top_layout)
        main_layout.addWidget(top_section)

        # --- file label (input) ---
        self.file_label_in = QLabel("No input file selected")
        self.file_label_in.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(self.file_label_in)

        # --- waveform + progress slider (input) ---
        waveform_container_in = QWidget()
        waveform_layout_in = QVBoxLayout()
        waveform_layout_in.setContentsMargins(0, 0, 0, 0)
        waveform_layout_in.setSpacing(4)
        waveform_container_in.setLayout(waveform_layout_in)

        self.waveform_in = WaveformWidget()
        waveform_layout_in.addWidget(self.waveform_in)

        self.position_slider_in = ClickableSlider(Qt.Horizontal)
        self.position_slider_in.setRange(0, 1000)
        self.position_slider_in.setValue(0)
        self.position_slider_in.setEnabled(False)

        self.position_slider_in.sliderPressed.connect(self.on_slider_pressed_in)
        self.position_slider_in.sliderReleased.connect(self.on_slider_released_in)

        waveform_layout_in.addWidget(self.position_slider_in)
        top_layout.addWidget(waveform_container_in)

        # --- transport + SCRAMBLE (input) ---
        buttons_layout_in = QHBoxLayout()

        self.open_button_in = QPushButton("Open")
        self.open_button_in.clicked.connect(self.on_open_clicked_in)
        buttons_layout_in.addWidget(self.open_button_in)

        self.play_button_in = QPushButton("Play ▶")
        self.play_button_in.clicked.connect(self.on_play_clicked_in)
        buttons_layout_in.addWidget(self.play_button_in)

        self.pause_button_in = QPushButton("Pause ❚❚")
        self.pause_button_in.clicked.connect(self.on_pause_resume_clicked_in)
        buttons_layout_in.addWidget(self.pause_button_in)

        self.stop_button_in = QPushButton("Stop ■")
        self.stop_button_in.clicked.connect(self.on_stop_clicked_in)
        buttons_layout_in.addWidget(self.stop_button_in)

        self.scramble_button = QPushButton("Scramble")
        self.scramble_button.clicked.connect(self.on_scramble_clicked)
        buttons_layout_in.addWidget(self.scramble_button)

        top_layout.addLayout(buttons_layout_in)

        # --- volume (input) ---
        volume_layout_in = QHBoxLayout()
        volume_label_in = QLabel("Volume")
        volume_layout_in.addWidget(volume_label_in)

        self.volume_slider_in = ClickableSlider(Qt.Horizontal)
        self.volume_slider_in.setRange(0, 100)
        self.volume_slider_in.setValue(50)
        self.volume_slider_in.valueChanged.connect(self.on_volume_changed_in)
        volume_layout_in.addWidget(self.volume_slider_in)

        top_layout.addLayout(volume_layout_in)

        # ========== BOTTOM SECTION (OUTPUT / SCRAMBLED) ==========
        bottom_section = QWidget()
        bottom_layout = QVBoxLayout()
        bottom_section.setLayout(bottom_layout)
        main_layout.addWidget(bottom_section)

        # --- file label (output) ---
        self.file_label_out = QLabel("No output file (scrambled) yet")
        self.file_label_out.setAlignment(Qt.AlignCenter)
        bottom_layout.addWidget(self.file_label_out)

        # --- waveform + progress slider (output) ---
        waveform_container_out = QWidget()
        waveform_layout_out = QVBoxLayout()
        waveform_layout_out.setContentsMargins(0, 0, 0, 0)
        waveform_layout_out.setSpacing(4)
        waveform_container_out.setLayout(waveform_layout_out)

        self.waveform_out = WaveformWidget()
        waveform_layout_out.addWidget(self.waveform_out)

        self.position_slider_out = ClickableSlider(Qt.Horizontal)
        self.position_slider_out.setRange(0, 1000)
        self.position_slider_out.setValue(0)
        self.position_slider_out.setEnabled(False)

        self.position_slider_out.sliderPressed.connect(self.on_slider_pressed_out)
        self.position_slider_out.sliderReleased.connect(self.on_slider_released_out)

        waveform_layout_out.addWidget(self.position_slider_out)
        bottom_layout.addWidget(waveform_container_out)

        # --- transport buttons (output) ---
        buttons_layout_out = QHBoxLayout()

        self.save_button_out = QPushButton("Save")
        self.save_button_out.clicked.connect(self.on_save_clicked_out)
        buttons_layout_out.addWidget(self.save_button_out)

        self.play_button_out = QPushButton("Play ▶")
        self.play_button_out.clicked.connect(self.on_play_clicked_out)
        buttons_layout_out.addWidget(self.play_button_out)

        self.pause_button_out = QPushButton("Pause ❚❚")
        self.pause_button_out.clicked.connect(self.on_pause_resume_clicked_out)
        buttons_layout_out.addWidget(self.pause_button_out)

        self.stop_button_out = QPushButton("Stop ■")
        self.stop_button_out.clicked.connect(self.on_stop_clicked_out)
        buttons_layout_out.addWidget(self.stop_button_out)

        # UNSCRAMBLE now in bottom section
        self.unscramble_button = QPushButton("Unscramble")
        self.unscramble_button.clicked.connect(self.on_unscramble_clicked)
        buttons_layout_out.addWidget(self.unscramble_button)

        bottom_layout.addLayout(buttons_layout_out)

        # --- volume (output) ---
        volume_layout_out = QHBoxLayout()
        volume_label_out = QLabel("Volume")
        volume_layout_out.addWidget(volume_label_out)

        self.volume_slider_out = ClickableSlider(Qt.Horizontal)
        self.volume_slider_out.setRange(0, 100)
        self.volume_slider_out.setValue(50)
        self.volume_slider_out.valueChanged.connect(self.on_volume_changed_out)
        volume_layout_out.addWidget(self.volume_slider_out)

        bottom_layout.addLayout(volume_layout_out)

    # ===================== BACKEND → UI (INPUT) =====================

    def on_player_duration_changed_in(self, duration_ms: int):
        print(f"[IN] Duration changed: {duration_ms} ms")
        self.track_duration_ms_in = duration_ms

        if duration_ms <= 0:
            self.position_slider_in.setEnabled(False)
            self.position_slider_in.setValue(0)
        else:
            self.position_slider_in.setEnabled(True)

    def on_player_position_changed_in(self, position_ms: int):
        if self.slider_is_pressed_in:
            return

        if self.track_duration_ms_in <= 0:
            self.position_slider_in.setValue(0)
            return

        slider_max = self.position_slider_in.maximum()
        fraction = position_ms / self.track_duration_ms_in
        fraction = max(0.0, min(1.0, fraction))
        value = int(fraction * slider_max)

        self.position_slider_in.blockSignals(True)
        self.position_slider_in.setValue(value)
        self.position_slider_in.blockSignals(False)

    # ===================== UI → BACKEND (INPUT SLIDER) =====================

    def on_slider_pressed_in(self):
        print("[IN] Slider pressed")
        self.slider_is_pressed_in = True

    def on_slider_released_in(self):
        print("[IN] Slider released")
        self.slider_is_pressed_in = False

        if self.track_duration_ms_in <= 0:
            return

        slider_max = self.position_slider_in.maximum()
        slider_value = self.position_slider_in.value()

        if slider_max <= 0:
            return

        fraction = slider_value / slider_max
        fraction = max(0.0, min(1.0, fraction))

        new_pos_ms = int(self.track_duration_ms_in * fraction)
        print(f"[IN] Seeking to {new_pos_ms} ms")
        self.audio_player_in.seek_ms(new_pos_ms)

    # ===================== BUTTONS (INPUT) =====================

    def on_open_clicked_in(self):
        print("[IN] Open button clicked")
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select input audio file",
            "",
            "Audio Files (*.wav);;All Files (*.*)"
        )

        if file_name:
            self.current_file_in = file_name
            print(f"[IN] Selected file: {file_name}")
            self.file_label_in.setText(file_name)

            self.audio_player_in.load_file(file_name)

            samples = load_waveform(file_name)
            if samples:
                print(f"[IN] Waveform loaded with {len(samples)} points")
            else:
                print("[IN] Waveform could not be loaded or is empty")
            self.waveform_in.set_samples(samples)

            self.playback_state_in = "stopped"
            self.is_paused_in = False
            self.pause_button_in.setText("Pause ❚❚")
            self.position_slider_in.setValue(0)
        else:
            print("[IN] No file selected")

    def on_play_clicked_in(self):
        print("[IN] Play ▶ button clicked")
        if self.current_file_in:
            print(f"[IN] Starting playback of: {self.current_file_in} (from beginning)")
            self.audio_player_in.play()
            self.playback_state_in = "playing"
            self.is_paused_in = False
            self.pause_button_in.setText("Pause ❚❚")
        else:
            print("[IN] No file selected to play")

    def on_pause_resume_clicked_in(self):
        if not self.is_paused_in:
            print("[IN] Pause ❚❚ button clicked")
            if self.playback_state_in == "playing":
                self.audio_player_in.pause()
                self.playback_state_in = "paused"
            self.is_paused_in = True
            self.pause_button_in.setText("Resume ▶")
        else:
            print("[IN] Resume ▶ button clicked")

            if self.playback_state_in == "paused":
                self.audio_player_in.resume()
                print("[IN] Resuming from paused position")
            elif self.playback_state_in == "stopped":
                if self.current_file_in:
                    print("[IN] Resuming after stop → restart from beginning")
                    self.audio_player_in.play()
                else:
                    print("[IN] No file selected to resume")
                    return

            self.playback_state_in = "playing"
            self.is_paused_in = False
            self.pause_button_in.setText("Pause ❚❚")

    def on_stop_clicked_in(self):
        print("[IN] Stop ■ button clicked")
        self.audio_player_in.stop()
        self.position_slider_in.setValue(0)
        self.playback_state_in = "stopped"
        self.is_paused_in = True
        self.pause_button_in.setText("Resume ▶")

    def on_volume_changed_in(self, value: int):
        print(f"[IN] Volume changed to: {value}")
        self.audio_player_in.set_volume_0_1(value / 100.0)

    # ===================== BACKEND → UI (OUTPUT) =====================

    def on_player_duration_changed_out(self, duration_ms: int):
        print(f"[OUT] Duration changed: {duration_ms} ms")
        self.track_duration_ms_out = duration_ms

        if duration_ms <= 0:
            self.position_slider_out.setEnabled(False)
            self.position_slider_out.setValue(0)
        else:
            self.position_slider_out.setEnabled(True)

    def on_player_position_changed_out(self, position_ms: int):
        if self.slider_is_pressed_out:
            return

        if self.track_duration_ms_out <= 0:
            self.position_slider_out.setValue(0)
            return

        slider_max = self.position_slider_out.maximum()
        fraction = position_ms / self.track_duration_ms_out
        fraction = max(0.0, min(1.0, fraction))
        value = int(fraction * slider_max)

        self.position_slider_out.blockSignals(True)
        self.position_slider_out.setValue(value)
        self.position_slider_out.blockSignals(False)

    # ===================== UI → BACKEND (OUTPUT SLIDER) =====================

    def on_slider_pressed_out(self):
        print("[OUT] Slider pressed")
        self.slider_is_pressed_out = True

    def on_slider_released_out(self):
        print("[OUT] Slider released")
        self.slider_is_pressed_out = False

        if self.track_duration_ms_out <= 0:
            return

        slider_max = self.position_slider_out.maximum()
        slider_value = self.position_slider_out.value()

        if slider_max <= 0:
            return

        fraction = slider_value / slider_max
        fraction = max(0.0, min(1.0, fraction))

        new_pos_ms = int(self.track_duration_ms_out * fraction)
        print(f"[OUT] Seeking to {new_pos_ms} ms")
        self.audio_player_out.seek_ms(new_pos_ms)

    # ===================== BUTTONS (OUTPUT) =====================

    def on_save_clicked_out(self):
        print("[OUT] Save button clicked")
        if not self.current_file_out:
            print("[OUT] No output audio to save")
            return

        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save output audio as",
            "",
            "Audio Files (*.wav);;All Files (*.*)"
        )

        if dest_path:
            shutil.copyfile(self.current_file_out, dest_path)
            print(f"[OUT] Saved current output audio to: {dest_path}")
            self.file_label_out.setText(dest_path)
        else:
            print("[OUT] Save canceled")

    def on_play_clicked_out(self):
        print("[OUT] Play ▶ button clicked")
        if self.current_file_out:
            print(f"[OUT] Starting playback of: {self.current_file_out} (from beginning)")
            self.audio_player_out.play()
            self.playback_state_out = "playing"
            self.is_paused_out = False
            self.pause_button_out.setText("Pause ❚❚")
        else:
            print("[OUT] No output file to play")

    def on_pause_resume_clicked_out(self):
        if not self.is_paused_out:
            print("[OUT] Pause ❚❚ button clicked")
            if self.playback_state_out == "playing":
                self.audio_player_out.pause()
                self.playback_state_out = "paused"
            self.is_paused_out = True
            self.pause_button_out.setText("Resume ▶")
        else:
            print("[OUT] Resume ▶ button clicked")

            if self.playback_state_out == "paused":
                self.audio_player_out.resume()
                print("[OUT] Resuming from paused position")
            elif self.playback_state_out == "stopped":
                if self.current_file_out:
                    print("[OUT] Resuming after stop → restart from beginning")
                    self.audio_player_out.play()
                else:
                    print("[OUT] No output file to resume")
                    return

            self.playback_state_out = "playing"
            self.is_paused_out = False
            self.pause_button_out.setText("Pause ❚❚")

    def on_stop_clicked_out(self):
        print("[OUT] Stop ■ button clicked")
        self.audio_player_out.stop()
        self.position_slider_out.setValue(0)
        self.playback_state_out = "stopped"
        self.is_paused_out = True
        self.pause_button_out.setText("Resume ▶")

    def on_volume_changed_out(self, value: int):
        print(f"[OUT] Volume changed to: {value}")
        self.audio_player_out.set_volume_0_1(value / 100.0)

    # ===================== SCRAMBLE / UNSCRAMBLE =====================

    def on_scramble_clicked(self):
        print("[SCRAMBLE] Scramble button clicked")
        if not self.current_file_in:
            print("[SCRAMBLE] No input file loaded")
            return

        # Scramble input → temporary scrambled file
        self.scrambler.scramble_file(self.current_file_in, self.scrambled_temp_path)

        # Load scrambled into bottom side
        self.current_file_out = self.scrambled_temp_path
        self.file_label_out.setText(self.scrambled_temp_path)

        samples_out = load_waveform(self.scrambled_temp_path)
        if samples_out:
            print(f"[SCRAMBLE] Scrambled waveform loaded with {len(samples_out)} points")
        else:
            print("[SCRAMBLE] Scrambled waveform empty")
        self.waveform_out.set_samples(samples_out)

        self.audio_player_out.load_file(self.scrambled_temp_path)

        self.playback_state_out = "stopped"
        self.is_paused_out = False
        self.position_slider_out.setValue(0)
        self.pause_button_out.setText("Pause ❚❚")
        self.is_out_scrambled = True

    def on_unscramble_clicked(self):
        print("[SCRAMBLE] Unscramble button clicked")
        if not self.current_file_out:
            print("[SCRAMBLE] No output file to unscramble")
            return

        if not self.is_out_scrambled:
            print("[SCRAMBLE] Current output is not marked as scrambled; nothing to unscramble")
            return

        # Unscramble bottom audio → temporary unscrambled file
        self.scrambler.unscramble_file(self.current_file_out, self.unscrambled_temp_path)

        # Load unscrambled into bottom side
        self.current_file_out = self.unscrambled_temp_path
        self.file_label_out.setText(self.unscrambled_temp_path)

        samples_out = load_waveform(self.unscrambled_temp_path)
        if samples_out:
            print(f"[SCRAMBLE] Unscrambled waveform loaded with {len(samples_out)} points")
        else:
            print("[SCRAMBLE] Unscrambled waveform empty")
        self.waveform_out.set_samples(samples_out)

        self.audio_player_out.load_file(self.unscrambled_temp_path)

        self.playback_state_out = "stopped"
        self.is_paused_out = False
        self.position_slider_out.setValue(0)
        self.pause_button_out.setText("Pause ❚❚")
        self.is_out_scrambled = False
