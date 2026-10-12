import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLabel, QLineEdit,
    QFileDialog, QMessageBox, QProgressBar, QAbstractItemView,
    QGroupBox, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from mutagen import File as MutagenFile


# Estensioni audio supportate
AUDIO_EXTENSIONS = {
    '.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma',
    '.opus', '.ape', '.mpc', '.aiff', '.aif', '.wv', '.tta'
}

# Codifiche supportate per il file .plc
# (etichetta mostrata nella GUI, nome codifica Python)
ENCODINGS = [
    ("cp1251 (Windows Cirillico - consigliato per AIMP 2 slavo)", "cp1251"),
    ("cp1252 (Windows Western - Europa/Italia)", "cp1252"),
    ("UTF-8 con BOM", "utf-8-sig"),
    ("UTF-16 con BOM", "utf-16"),
    ("UTF-8 senza BOM", "utf-8"),
]


def sanitize_for_encoding(text, encoding):
    if not isinstance(text, str):
        text = str(text)

    result = []
    problems = []

    for ch in text:
        try:
            ch.encode(encoding)
            result.append(ch)
        except (UnicodeEncodeError, LookupError):
            problems.append(ch)
            # Prova a sostituire con un carattere simile o '?'
            result.append('?')

    return ''.join(result), problems


def safe_write(path, text, encoding):
    cleaned, problems = sanitize_for_encoding(text, encoding)
    with open(path, 'w', encoding=encoding, newline='') as f:
        f.write(cleaned)
    return problems


class PlaylistWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(str, list)  # path, lista_problemi
    error = pyqtSignal(str)

    def __init__(self, playlist_name, files, output_path, encoding):
        super().__init__()
        self.playlist_name = playlist_name
        self.files = files
        self.output_path = output_path
        self.encoding = encoding
        self.all_problems = set()

    def get_audio_metadata(self, filepath):
        metadata = {
            'artist': '',
            'album': '',
            'year': '',
            'title': os.path.splitext(os.path.basename(filepath))[0],
            'duration_ms': 0,
            'size': 0,
            'sample_rate': 44100,
            'bitrate': 128,
            'channels': 2
        }

        try:
            metadata['size'] = os.path.getsize(filepath)
            audio = MutagenFile(filepath)

            if audio is not None:
                if audio.info:
                    if hasattr(audio.info, 'length') and audio.info.length:
                        metadata['duration_ms'] = int(audio.info.length * 1000)
                    if hasattr(audio.info, 'sample_rate') and audio.info.sample_rate:
                        metadata['sample_rate'] = audio.info.sample_rate
                    if hasattr(audio.info, 'bitrate') and audio.info.bitrate:
                        br = audio.info.bitrate
                        metadata['bitrate'] = int(br / 1000) if br > 10000 else int(br)
                    if hasattr(audio.info, 'channels') and audio.info.channels:
                        metadata['channels'] = audio.info.channels

                if audio.tags:
                    for key in audio.tags.keys():
                        key_lower = key.lower()
                        try:
                            value = audio.tags[key]
                            if isinstance(value, list):
                                text = str(value[0]) if value else ''
                            else:
                                text = str(value)

                            if 'artist' in key_lower and not metadata['artist']:
                                metadata['artist'] = text
                            elif ('album' in key_lower and 'artist' not in key_lower
                                  and not metadata['album']):
                                metadata['album'] = text
                            elif 'title' in key_lower and (
                                    not metadata['title'] or
                                    metadata['title'] == os.path.splitext(
                                        os.path.basename(filepath))[0]):
                                metadata['title'] = text
                            elif (('date' in key_lower or 'year' in key_lower)
                                  and not metadata['year']):
                                metadata['year'] = text[:4] if text else ''
                        except Exception:
                            continue
        except Exception as e:
            print(f"Errore metadati {filepath}: {e}")

        return metadata

    def run(self):
        try:
            lines = [f"<{self.playlist_name}:0>"]
            total = len(self.files)

            for i, filepath in enumerate(self.files):
                self.progress.emit(i + 1, total, os.path.basename(filepath))

                if not os.path.isfile(filepath):
                    continue

                meta = self.get_audio_metadata(filepath)

                line_parts = [
                    "1",
                    filepath,
                    meta['artist'],
                    meta['album'],
                    meta['year'],
                    meta['title'],
                    str(meta['duration_ms']),
                    str(meta['size']),
                    "",
                    "",
                    str(meta['sample_rate']),
                    str(meta['bitrate']),
                    str(meta['channels'])
                ]

                lines.append("|".join(line_parts))

            full_text = "\n".join(lines)
            problems = safe_write(self.output_path, full_text, self.encoding)

            # Raccogli i caratteri problematici unici con la loro descrizione
            problem_info = []
            for ch in sorted(set(problems)):
                problem_info.append((ch, f"U+{ord(ch):04X}"))

            self.finished_ok.emit(self.output_path, problem_info)

        except Exception as e:
            self.error.emit(str(e))


class AIMPPlaylistGenerator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AIMP 2 - Generatore Playlist .plc")
        self.setMinimumSize(900, 720)
        self.files = []
        self.worker = None

        self.init_ui()
        self.apply_style()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # --- Titolo ---
        title = QLabel("🎵 Generatore Playlist AIMP 2 (.plc)")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # --- Gruppo Nome Playlist ---
        name_group = QGroupBox("Nome Playlist")
        name_layout = QHBoxLayout(name_group)
        name_layout.addWidget(QLabel("Nome:"))
        self.name_input = QLineEdit("La_Mia_Playlist")
        self.name_input.setPlaceholderText("Inserisci il nome della playlist")
        name_layout.addWidget(self.name_input)
        main_layout.addWidget(name_group)

        # --- Gruppo Codifica ---
        enc_group = QGroupBox("Codifica File .plc")
        enc_layout = QHBoxLayout(enc_group)
        enc_layout.addWidget(QLabel("Codifica:"))
        self.encoding_combo = QComboBox()
        for label, code in ENCODINGS:
            self.encoding_combo.addItem(label, code)
        self.encoding_combo.setCurrentIndex(0)  # cp1251 di default
        enc_layout.addWidget(self.encoding_combo, 1)
        main_layout.addWidget(enc_group)

        # --- Gruppo Pulsanti Aggiunta ---
        btn_group = QGroupBox("Aggiungi Brani")
        btn_layout = QHBoxLayout(btn_group)

        self.btn_add_files = QPushButton("📄 Aggiungi File")
        self.btn_add_files.clicked.connect(self.add_files)

        self.btn_add_folder = QPushButton("📁 Aggiungi Cartella")
        self.btn_add_folder.clicked.connect(self.add_folder)

        self.btn_add_folder_recursive = QPushButton("📂 Aggiungi Cartella (Ricorsiva)")
        self.btn_add_folder_recursive.clicked.connect(self.add_folder_recursive)

        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_add_folder)
        btn_layout.addWidget(self.btn_add_folder_recursive)
        main_layout.addWidget(btn_group)

        # --- Opzioni ---
        opt_group = QGroupBox("Opzioni")
        opt_layout = QHBoxLayout(opt_group)
        self.chk_skip_duplicates = QCheckBox("Salta duplicati")
        self.chk_skip_duplicates.setChecked(True)
        self.chk_sort = QCheckBox("Ordina alfabeticamente")
        opt_layout.addWidget(self.chk_skip_duplicates)
        opt_layout.addWidget(self.chk_sort)
        opt_layout.addStretch()
        main_layout.addWidget(opt_group)

        # --- Lista File ---
        list_group = QGroupBox("Brani nella Playlist")
        list_layout = QVBoxLayout(list_group)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setAlternatingRowColors(True)
        list_layout.addWidget(self.file_list)

        list_btn_layout = QHBoxLayout()
        self.btn_remove = QPushButton("❌ Rimuovi Selezionati")
        self.btn_remove.clicked.connect(self.remove_selected)

        self.btn_clear = QPushButton("🗑️ Svuota Lista")
        self.btn_clear.clicked.connect(self.clear_list)

        self.btn_up = QPushButton("⬆️ Su")
        self.btn_up.clicked.connect(lambda: self.move_item(-1))

        self.btn_down = QPushButton("⬇️ Giù")
        self.btn_down.clicked.connect(lambda: self.move_item(1))

        list_btn_layout.addWidget(self.btn_up)
        list_btn_layout.addWidget(self.btn_down)
        list_btn_layout.addWidget(self.btn_remove)
        list_btn_layout.addWidget(self.btn_clear)
        list_layout.addLayout(list_btn_layout)

        main_layout.addWidget(list_group)

        # --- Label conteggio ---
        self.count_label = QLabel("Totale brani: 0")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(self.count_label)

        # --- Progress Bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Pronto.")
        main_layout.addWidget(self.status_label)

        # --- Pulsante Genera ---
        self.btn_generate = QPushButton("💾 Genera Playlist .plc")
        self.btn_generate.setMinimumHeight(45)
        self.btn_generate.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.btn_generate.clicked.connect(self.generate_playlist)
        main_layout.addWidget(self.btn_generate)

    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; }
            QWidget { color: #e0e0e0; font-family: 'Segoe UI'; font-size: 10pt; }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #4ea1ff;
            }
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 6px 12px;
                color: #e0e0e0;
            }
            QPushButton:hover { background-color: #4a4a4a; border-color: #4ea1ff; }
            QPushButton:pressed { background-color: #2a2a2a; }
            QPushButton:disabled { color: #777; background-color: #333; }
            QLineEdit, QComboBox {
                background-color: #1e1e1e;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px;
                color: #e0e0e0;
            }
            QLineEdit:focus, QComboBox:focus { border-color: #4ea1ff; }
            QComboBox QAbstractItemView {
                background-color: #1e1e1e;
                color: #e0e0e0;
                selection-background-color: #4ea1ff;
            }
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item { padding: 3px; }
            QListWidget::item:selected { background-color: #4ea1ff; color: #fff; }
            QListWidget::item:alternate { background-color: #262626; }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
                background-color: #1e1e1e;
            }
            QProgressBar::chunk { background-color: #4ea1ff; border-radius: 3px; }
            QCheckBox { spacing: 8px; }
            QLabel { background: transparent; }
        """)

    # ---------- Logica di aggiunta ----------

    def is_audio_file(self, path):
        return Path(path).suffix.lower() in AUDIO_EXTENSIONS

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleziona File Audio",
            "",
            "File Audio (*.mp3 *.flac *.wav *.ogg *.m4a *.aac *.wma *.opus *.ape *.mpc *.aiff *.aif *.wv *.tta);;Tutti i File (*.*)"
        )
        if files:
            self.add_paths_to_list(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleziona Cartella")
        if folder:
            files = []
            for entry in os.scandir(folder):
                if entry.is_file() and self.is_audio_file(entry.path):
                    files.append(entry.path)
            if not files:
                QMessageBox.information(self, "Nessun file",
                                        "Nessun file audio trovato nella cartella selezionata.")
                return
            self.add_paths_to_list(files)

    def add_folder_recursive(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleziona Cartella (Ricorsiva)")
        if folder:
            files = []
            for root, _, filenames in os.walk(folder):
                for fname in filenames:
                    full = os.path.join(root, fname)
                    if self.is_audio_file(full):
                        files.append(full)
            if not files:
                QMessageBox.information(self, "Nessun file",
                                        "Nessun file audio trovato nella cartella selezionata.")
                return
            self.add_paths_to_list(files)

    def add_paths_to_list(self, paths):
        added = 0
        duplicates = 0
        existing = set(self.files) if self.chk_skip_duplicates.isChecked() else None

        for p in paths:
            ap = os.path.abspath(p)
            if existing is not None and ap in existing:
                duplicates += 1
                continue
            self.files.append(ap)
            if existing is not None:
                existing.add(ap)
            added += 1

        if self.chk_sort.isChecked():
            self.files.sort(key=lambda x: os.path.basename(x).lower())

        self.refresh_list()

        msg = f"Aggiunti {added} brani."
        if duplicates:
            msg += f" ({duplicates} duplicati saltati)"
        self.status_label.setText(msg)

    def refresh_list(self):
        self.file_list.clear()
        for path in self.files:
            item = QListWidgetItem(f"🎵 {os.path.basename(path)}   —   {path}")
            item.setToolTip(path)
            self.file_list.addItem(item)
        self.count_label.setText(f"Totale brani: {len(self.files)}")

    def remove_selected(self):
        rows = sorted({self.file_list.row(i) for i in self.file_list.selectedItems()},
                      reverse=True)
        for row in rows:
            if 0 <= row < len(self.files):
                self.files.pop(row)
        self.refresh_list()

    def clear_list(self):
        if not self.files:
            return
        reply = QMessageBox.question(
            self, "Conferma", "Vuoi svuotare completamente la lista?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.files.clear()
            self.refresh_list()

    def move_item(self, direction):
        rows = sorted({self.file_list.row(i) for i in self.file_list.selectedItems()})
        if not rows:
            return
        if direction == -1 and rows[0] == 0:
            return
        if direction == 1 and rows[-1] == len(self.files) - 1:
            return

        if direction == -1:
            for row in rows:
                self.files[row - 1], self.files[row] = self.files[row], self.files[row - 1]
            new_rows = [r - 1 for r in rows]
        else:
            for row in reversed(rows):
                self.files[row + 1], self.files[row] = self.files[row], self.files[row + 1]
            new_rows = [r + 1 for r in rows]

        self.refresh_list()
        for r in new_rows:
            if 0 <= r < self.file_list.count():
                self.file_list.item(r).setSelected(True)

    # ---------- Generazione ----------

    def generate_playlist(self):
        if not self.files:
            QMessageBox.warning(self, "Attenzione",
                                "Aggiungi almeno un brano alla playlist.")
            return

        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Attenzione",
                                "Inserisci un nome per la playlist.")
            return

        encoding = self.encoding_combo.currentData()

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salva Playlist",
            f"{name}.plc",
            "Playlist AIMP 2 (*.plc);;Tutti i File (*.*)"
        )
        if not output_path:
            return

        if not output_path.lower().endswith('.plc'):
            output_path += '.plc'

        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.files))
        self.progress_bar.setValue(0)

        self.worker = PlaylistWorker(name, list(self.files), output_path, encoding)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, current, total, filename):
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Elaborazione {current}/{total}: {filename}")

    def on_finished(self, output_path, problems):
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"✅ Playlist salvata: {output_path}")

        msg = f"Playlist creata con successo:\n{output_path}"

        if problems:
            msg += "\n\n⚠️ Alcuni caratteri non erano rappresentabili nella codifica scelta e sono stati sostituiti con '?':\n"
            # Mostra massimo 20 caratteri diversi
            for ch, code in problems[:20]:
                msg += f"  • '{ch}' ({code})\n"
            if len(problems) > 20:
                msg += f"  ... e altri {len(problems) - 20} caratteri diversi.\n"
            msg += "\nSe la playlist non funziona, prova un'altra codifica nel menu a tendina."

        msg += "\n\nVuoi aprire la cartella di destinazione?"

        reply = QMessageBox.question(
            self, "Completato", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            folder = os.path.dirname(output_path)
            if sys.platform == 'win32':
                os.startfile(folder)
            elif sys.platform == 'darwin':
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')

    def on_error(self, msg):
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("❌ Errore durante la generazione.")
        QMessageBox.critical(self, "Errore", f"Errore durante la generazione:\n{msg}")

    def set_ui_enabled(self, enabled):
        for w in (self.btn_add_files, self.btn_add_folder,
                  self.btn_add_folder_recursive, self.btn_generate,
                  self.btn_remove, self.btn_clear, self.btn_up,
                  self.btn_down, self.name_input, self.file_list,
                  self.encoding_combo):
            w.setEnabled(enabled)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = AIMPPlaylistGenerator()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
