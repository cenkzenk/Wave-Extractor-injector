import os
import json
import struct
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar,
    QTextEdit, QMessageBox, QPushButton, QHBoxLayout, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDir

EXTRACT_DIR_NAME = "extracted_wavs" # Klasör adını sabitledik
INDEX_FILE = "wav_index.json"
FILL_BYTE = b'\x00'


class WAVProcessor(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str)
    update_counter = pyqtSignal(int)
    set_status_label = pyqtSignal(str) # Durum etiketi için yeni sinyal

    def __init__(self, mode, base_dir):
        super().__init__()
        self.mode = mode
        self.base_dir = base_dir
        self.wav_count = 0

    def run(self):
        if self.mode == 'extract':
            self.scan_and_extract()
        elif self.mode == 'inject':
            self.inject_back()

    def scan_and_extract(self):
        extract_dir_path = os.path.join(self.base_dir, EXTRACT_DIR_NAME)
        os.makedirs(extract_dir_path, exist_ok=True)
        wav_index = []
        self.wav_count = 0
        self.set_status_label.emit("Taranıyor...")

        all_files = []
        # Sadece belirtilen dizindeki dosyaları tara, alt dizinlere inme
        # Eğer alt dizinleri de taramak isterseniz os.walk kullanmaya devam edebilirsiniz.
        # for root, _, files in os.walk(self.base_dir):
        #     for file in files:
        #         full_path = os.path.join(root, file)
        #         if full_path.endswith(".py") or INDEX_FILE in full_path or EXTRACT_DIR_NAME in full_path:
        #             continue
        #         all_files.append(full_path)

        # Sadece base_dir'deki dosyaları tara
        try:
            for file in os.listdir(self.base_dir):
                full_path = os.path.join(self.base_dir, file)
                if os.path.isfile(full_path) and not (full_path.endswith(".py") or file == INDEX_FILE):
                     all_files.append(full_path)
        except Exception as e:
             self.log.emit(f"[!] Dizin okunurken hata oluştu: {e}")
             self.finished.emit("Tarama işlemi tamamlanamadı.")
             return


        total = len(all_files)
        if total == 0:
            self.finished.emit(f"'{self.base_dir}' dizininde taranacak dosya bulunamadı.")
            self.set_status_label.emit("Tarama tamamlandı.")
            return

        done = 0
        for path in all_files:
            self.log.emit(f"[+] Taranıyor: {path}")
            try:
                with open(path, 'rb') as f:
                    data = f.read()

                offset = 0
                original_file_modified = False # Dosyanın değiştirilip değiştirilmediğini takip et

                while offset < len(data) - 12:
                    # WAV başlığı kontrolü: "RIFF" (offset) ve "WAVE" (offset + 8)
                    if data[offset:offset+4] == b'RIFF' and data[offset+8:offset+12] == b'WAVE':
                         # RIFF chunk boyutu (4 bayt, little-endian, offset + 4) + 'RIFF' ve boyut alanlarının kendisi (8 bayt)
                        try:
                            size = struct.unpack('<I', data[offset+4:offset+8])[0] + 8
                            end = offset + size
                        except struct.error:
                             self.log.emit(f"    [!] Hata: '{path}' dosyasında geçersiz boyut bilgisi @ {offset}.")
                             offset += 1 # Hatalı chunk'ı atla
                             continue

                        if end > len(data):
                            self.log.emit(f"    [!] Hata: '{path}' dosyasında belirtilen WAV boyutu dosya sınırlarını aşıyor @ {offset}.")
                            break # Bu dosyada daha fazla arama
                            # offset += 1 # Alternatif olarak 1 byte atla ve devam et

                        wav_data = data[offset:end]

                        # Geçersiz RIFF boyutu kontrolü (çok küçük veya çok büyük)
                        # Gerçekçi bir WAV dosyasının minimum boyutu 36 bayttır (RIFF + WAVE + fmt + data chunk başlıkları)
                        # Çok büyük boyutlar genellikle dosya bozulmalarını veya yanlış eşleşmeleri gösterir.
                        # Buraya daha spesifik kontroller eklenebilir, örneğin 'fmt ' chunk'ını aramak.
                        if size < 36 or size > 50*1024*1024: # Örnek: max 50MB WAV
                             self.log.emit(f"    [!] Şüpheli WAV boyutu ({size} bayt) bulundu: '{path}' @ {offset}. Atlanıyor.")
                             offset += 1
                             continue

                        extract_name = f"{os.path.basename(path)}_{offset}.wav"
                        extract_path = os.path.join(extract_dir_path, extract_name)

                        # Çıkarılacak dosyanın zaten var olup olmadığını kontrol et
                        if os.path.exists(extract_path):
                            self.log.emit(f"    -> WAV zaten çıkarılmış: {extract_name}. Atlanıyor.")
                        else:
                            with open(extract_path, 'wb') as out:
                                out.write(wav_data)

                            # Orijinal dosyayı sıfırla
                            with open(path, 'r+b') as f:
                                f.seek(offset)
                                f.write(FILL_BYTE * size)
                            original_file_modified = True # Dosya değiştirildi

                            self.log.emit(f"    -> WAV bulundu ve çıkarıldı: {extract_name}")
                            self.wav_count += 1
                            self.update_counter.emit(self.wav_count)

                        wav_index.append({
                            'file_path': path,
                            'offset': offset,
                            'length': size,
                            'extract_path': extract_path
                        })
                        offset = end # Bir sonraki potansiyel WAV başlangıcı, bulunan WAV'ın bitişi sonrası
                    else:
                        offset += 1 # 1 bayt ileri git ve yeniden tara
            except PermissionError:
                 self.log.emit(f"[!] Erişim Reddedildi: {path}. Atlanıyor.")
            except Exception as e:
                self.log.emit(f"[!] HATA işlenirken: {path} - {e}")

            done += 1
            self.progress.emit(int((done / total) * 100))

        # Sadece değişiklik yapıldıysa index dosyasını yaz
        # if original_file_modified or self.wav_count > 0: # En az bir wav bulunduysa veya dosya değiştirildiyse
        try:
            with open(os.path.join(self.base_dir, INDEX_FILE), 'w') as f:
                json.dump(wav_index, f, indent=2)
            self.log.emit(f"[+] İndeks dosyası oluşturuldu: {INDEX_FILE}")
        except Exception as e:
             self.log.emit(f"[!] İndeks dosyası yazılırken hata oluştu: {e}")


        self.finished.emit(f"{self.wav_count} adet gömülü .wav çıkarıldı ve sıfırlandı.")
        self.set_status_label.emit("Tarama tamamlandı.")


    def inject_back(self):
        index_file_path = os.path.join(self.base_dir, INDEX_FILE)
        extract_dir_path = os.path.join(self.base_dir, EXTRACT_DIR_NAME)

        self.set_status_label.emit("Inject ediliyor...")

        if not os.path.exists(index_file_path):
            self.finished.emit(f"Kayıt dosyası bulunamadı: '{INDEX_FILE}'. Inject işlemi yapılamıyor.")
            self.set_status_label.emit("Inject tamamlanamadı.")
            return

        if not os.path.exists(extract_dir_path):
             self.finished.emit(f"Çıkarılan WAV klasörü bulunamadı: '{EXTRACT_DIR_NAME}'. Inject işlemi yapılamıyor.")
             self.set_status_label.emit("Inject tamamlanamadı.")
             return


        try:
            with open(index_file_path, 'r') as f:
                entries = json.load(f)
        except json.JSONDecodeError:
            self.finished.emit(f"Kayıt dosyası bozuk: '{INDEX_FILE}'. Inject işlemi yapılamıyor.")
            self.set_status_label.emit("Inject tamamlanamadı.")
            return
        except Exception as e:
            self.finished.emit(f"Kayıt dosyası okunurken hata oluştu: '{INDEX_FILE}' - {e}. Inject işlemi yapılamıyor.")
            self.set_status_label.emit("Inject tamamlanamadı.")
            return


        total = len(entries)
        if total == 0:
            self.finished.emit("Kayıt dosyasında inject edilecek giriş bulunamadı.")
            self.set_status_label.emit("Inject tamamlandı.")
            return

        done = 0
        self.wav_count = total
        self.update_counter.emit(self.wav_count)

        for item in entries:
            extract_file_full_path = item.get('extract_path')
            original_file_full_path = item.get('file_path')
            offset = item.get('offset')
            length = item.get('length')

            # Eksik bilgi kontrolü
            if extract_file_full_path is None or original_file_full_path is None or offset is None or length is None:
                 self.log.emit(f"[!] Kayıt dosyasında eksik bilgi bulundu: {item}. Atlanıyor.")
                 done += 1
                 self.progress.emit(int((done / total) * 100))
                 continue

            # Dosya varlığı kontrolü
            if not os.path.exists(extract_file_full_path):
                 self.log.emit(f"[!] Çıkarılan WAV dosyası bulunamadı: {extract_file_full_path}. Atlanıyor.")
                 done += 1
                 self.progress.emit(int((done / total) * 100))
                 continue

            if not os.path.exists(original_file_full_path):
                 self.log.emit(f"[!] Orijinal hedef dosya bulunamadı: {original_file_full_path}. Atlanıyor.")
                 done += 1
                 self.progress.emit(int((done / total) * 100))
                 continue

            try:
                with open(extract_file_full_path, 'rb') as ex:
                    data = ex.read()

                if len(data) != length:
                    self.log.emit(f"[!] Uyuşmayan uzunluk: '{extract_file_full_path}' (beklenen: {length}, bulunan: {len(data)}). Atlanıyor.")
                    # continue # Uyuşmazlık durumunda inject etmeyelim
                else:
                     with open(original_file_full_path, 'r+b') as f:
                        f.seek(offset)
                        f.write(data)
                     self.log.emit(f"[+] Inject edildi: {os.path.basename(original_file_full_path)} @ {offset}")

            except PermissionError:
                 self.log.emit(f"[!] Erişim Reddedildi: {original_file_full_path}. Atlanıyor.")
            except Exception as e:
                self.log.emit(f"[!] Inject hatası: {original_file_full_path} @ {offset} - {e}")

            done += 1
            self.progress.emit(int((done / total) * 100))

        self.finished.emit(f"{total} adet .wav orijinal dosyalara geri inject edildi.")
        self.set_status_label.emit("Inject tamamlandı.")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gömülü WAV Çıkarıcı / Injector")
        self.setGeometry(300, 300, 700, 500) # Pencere boyutunu biraz büyüttük

        layout = QVBoxLayout()

        # Dizin Seçimi
        dir_layout = QHBoxLayout()
        self.dir_label = QLabel("İşlem Dizini: Mevcut Dizin")
        self.dir_button = QPushButton("Dizin Seç...")
        self.dir_button.clicked.connect(self.select_directory)
        dir_layout.addWidget(self.dir_label)
        dir_layout.addWidget(self.dir_button)
        layout.addLayout(dir_layout)

        self.base_directory = os.getcwd() # Başlangıç dizini

        self.label = QLabel("Yapmak istediğiniz işlemi seçin.")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        self.counter_label = QLabel("Bulunan/Inject Edilen WAV: 0")
        self.counter_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.counter_label)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Butonlar
        button_layout = QHBoxLayout()
        self.extract_button = QPushButton("WAV'ları Çıkar (Boşalt)")
        self.inject_button = QPushButton("WAV'ları Geri Inject Et")

        button_layout.addWidget(self.extract_button)
        button_layout.addWidget(self.inject_button)
        layout.addLayout(button_layout)

        self.extract_button.clicked.connect(lambda: self.start_processing('extract'))
        self.inject_button.clicked.connect(lambda: self.start_processing('inject'))

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        self.setLayout(layout)

        self.worker = None # Worker thread'i burada saklayacağız


    def select_directory(self):
        # QFileDialog.getExistingDirectory kullanıcının bir dizin seçmesini sağlar
        directory = QFileDialog.getExistingDirectory(self, "İşlem Yapılacak Dizini Seçin", self.base_directory)
        if directory:
            self.base_directory = directory
            self.dir_label.setText(f"İşlem Dizini: {self.base_directory}")
            self.log_box.append(f"[+] İşlem dizini değiştirildi: {self.base_directory}")
            # Dizin değiştiğinde sayaçı sıfırlayabiliriz veya duruma göre güncelleyebiliriz.
            # Şimdilik sadece dizini güncelledik. Sayaç bir sonraki işlemde güncellenecek.


    def start_processing(self, mode):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "İşlem Devam Ediyor", "Şu anda bir işlem devam ediyor. Lütfen bekleyin.")
            return

        # Inject öncesi kontrol
        if mode == 'inject':
            index_file_path = os.path.join(self.base_directory, INDEX_FILE)
            extract_dir_path = os.path.join(self.base_directory, EXTRACT_DIR_NAME)
            if not os.path.exists(index_file_path) or not os.path.exists(extract_dir_path):
                missing = []
                if not os.path.exists(index_file_path):
                    missing.append(INDEX_FILE)
                if not os.path.exists(extract_dir_path):
                     missing.append(EXTRACT_DIR_NAME)

                QMessageBox.warning(self, "Eksik Dosyalar/Klasör",
                                   f"Inject işlemi için gerekli olan dosya/klasör(ler) bulunamadı:\n{', '.join(missing)}\n"
                                   "Lütfen önce 'WAV'ları Çıkar' işlemini çalıştırın.")
                return

        self.log_box.clear() # Yeni işlem başladığında logu temizle
        self.progress.setValue(0)
        self.counter_label.setText("Bulunan/Inject Edilen WAV: 0")
        self.label.setText("İşlem başlatılıyor...")

        # Butonları devre dışı bırak
        self.extract_button.setEnabled(False)
        self.inject_button.setEnabled(False)
        self.dir_button.setEnabled(False)

        self.worker = WAVProcessor(mode, self.base_directory)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.on_finished)
        self.worker.log.connect(self.append_log)
        self.worker.update_counter.connect(self.update_wav_count)
        self.worker.set_status_label.connect(self.label.setText) # Yeni sinyal bağlantısı
        self.worker.start()

    def append_log(self, text):
        # Scrollbar'ın otomatik olarak en aşağı inmesini sağla
        self.log_box.append(text)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())


    def update_wav_count(self, count):
        self.counter_label.setText(f"Bulunan/Inject Edilen WAV: {count}")

    def on_finished(self, message):
        # İşlem bittiğinde butonları tekrar etkinleştir
        self.extract_button.setEnabled(True)
        self.inject_button.setEnabled(True)
        self.dir_button.setEnabled(True)

        # Son mesajı ana etikete yaz
        self.label.setText(message)
        # İsteğe bağlı: İşlem bittiğinde bir bilgi kutusu göster
        # QMessageBox.information(self, "İşlem Tamamlandı", message)
        self.log_box.append("[+] İşlem tamamlandı.")


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
