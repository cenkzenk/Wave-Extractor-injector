import os
import json
import struct
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar,
    QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

EXTRACT_DIR = "extracted_wavs"
INDEX_FILE = "wav_index.json"
FILL_BYTE = b'\x00'


class WAVProcessor(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str)
    update_counter = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.base_dir = os.getcwd()
        self.wav_count = 0

    def run(self):
        if os.path.exists(INDEX_FILE):
            self.inject_back()
        else:
            self.scan_and_extract()

    def scan_and_extract(self):
        os.makedirs(EXTRACT_DIR, exist_ok=True)
        wav_index = []
        self.wav_count = 0

        all_files = []
        for root, _, files in os.walk(self.base_dir):
            for file in files:
                full_path = os.path.join(root, file)
                if full_path.endswith(".py") or INDEX_FILE in full_path:
                    continue
                all_files.append(full_path)

        total = len(all_files)
        if total == 0:
            self.finished.emit("Tarayacak dosya bulunamadı.")
            return

        done = 0
        for path in all_files:
            self.log.emit(f"[+] Taranıyor: {path}")
            try:
                with open(path, 'rb') as f:
                    data = f.read()

                offset = 0
                while offset < len(data) - 12:
                    if data[offset:offset+4] == b'RIFF' and data[offset+8:offset+12] == b'WAVE':
                        size = struct.unpack('<I', data[offset+4:offset+8])[0] + 8
                        end = offset + size
                        if end > len(data):
                            break
                        wav_data = data[offset:end]

                        extract_name = f"{os.path.basename(path)}_{offset}.wav"
                        extract_path = os.path.join(EXTRACT_DIR, extract_name)
                        with open(extract_path, 'wb') as out:
                            out.write(wav_data)

                        with open(path, 'r+b') as f:
                            f.seek(offset)
                            f.write(FILL_BYTE * size)

                        wav_index.append({
                            'file_path': path,
                            'offset': offset,
                            'length': size,
                            'extract_path': extract_path
                        })
                        self.wav_count += 1
                        self.update_counter.emit(self.wav_count)
                        self.log.emit(f"    -> WAV bulundu ve çıkarıldı: {extract_name}")
                        offset = end
                    else:
                        offset += 1
            except Exception as e:
                self.log.emit(f"[!] HATA: {path} - {e}")

            done += 1
            self.progress.emit(int((done / total) * 100))

        with open(INDEX_FILE, 'w') as f:
            json.dump(wav_index, f, indent=2)

        self.finished.emit(f"{self.wav_count} adet gömülü .wav çıkarıldı ve sıfırlandı.")

    def inject_back(self):
        try:
            with open(INDEX_FILE, 'r') as f:
                entries = json.load(f)
        except:
            self.finished.emit("Kayıt dosyası bozuk veya bulunamadı.")
            return

        total = len(entries)
        done = 0
        self.wav_count = total
        self.update_counter.emit(self.wav_count)

        for item in entries:
            try:
                with open(item['extract_path'], 'rb') as ex:
                    data = ex.read()
                if len(data) != item['length']:
                    self.log.emit(f"[!] Uyuşmayan uzunluk: {item['extract_path']}")
                    continue
                with open(item['file_path'], 'r+b') as f:
                    f.seek(item['offset'])
                    f.write(data)
                self.log.emit(f"[+] Inject edildi: {item['file_path']} @ {item['offset']}")
            except Exception as e:
                self.log.emit(f"[!] Inject hatası: {e}")

            done += 1
            self.progress.emit(int((done / total) * 100))

        self.finished.emit(f"{total} adet .wav orijinal dosyalara geri inject edildi.")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Embedded WAV Extractor / Injector")
        self.setGeometry(300, 300, 600, 400)

        layout = QVBoxLayout()

        self.label = QLabel("İşlem başlatılıyor...")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        self.counter_label = QLabel("Bulunan WAV: 0")
        self.counter_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.counter_label)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        self.setLayout(layout)

        self.worker = WAVProcessor()
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.on_finished)
        self.worker.log.connect(self.append_log)
        self.worker.update_counter.connect(self.update_wav_count)
        self.worker.start()

    def append_log(self, text):
        self.log_box.append(text)

    def update_wav_count(self, count):
        self.counter_label.setText(f"Bulunan WAV: {count}")

    def on_finished(self, message):
        self.label.setText(message)
        QMessageBox.information(self, "Tamamlandı", message)


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
