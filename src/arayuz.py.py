import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QTextEdit, QSplashScreen,
    QGraphicsView, QGraphicsScene, QStackedWidget, QSplitter
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QPalette, QPen, QBrush, QPixmap, QPainter
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve

class ProfesyonelSplash(QSplashScreen):
    """Modern, animasyonlu açılış ekranı"""
    def __init__(self):
        self.pixmap = QPixmap(800, 600)
        self.pixmap.fill(QColor("#0a1929"))
        super().__init__(self.pixmap)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self._ciz_logo()
        self.setWindowOpacity(1.0)
        
    def _ciz_logo(self):
        painter = QPainter(self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Logo çizimi
        painter.setPen(QPen(QColor("#2196f3"), 3))
        painter.setBrush(QBrush(QColor("#1565c0")))
        painter.drawEllipse(350, 150, 100, 100)
        painter.setBrush(QBrush(QColor("#64b5f6")))
        painter.drawEllipse(375, 175, 20, 20)
        painter.drawEllipse(405, 175, 20, 20)
        
        # Metinler
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 32, QFont.Weight.Bold))
        painter.drawText(self.pixmap.rect().adjusted(0, 100, 0, 0), 
                        Qt.AlignmentFlag.AlignCenter, "EYECONTROL OS")
        painter.setPen(QColor("#64b5f6"))
        painter.setFont(QFont("Segoe UI", 14))
        painter.drawText(self.pixmap.rect().adjusted(0, 180, 0, 0), 
                        Qt.AlignmentFlag.AlignCenter, "Hypervisor Kontrol Sistemi v2.0")
        
        # Progress bar
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#1e3a5f")))
        painter.drawRoundedRect(250, 450, 300, 6, 3, 3)
        painter.setBrush(QBrush(QColor("#2196f3")))
        painter.drawRoundedRect(250, 450, 0, 6, 3, 3)
        painter.end()
        
    def animasyon_baslat(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._progress_guncelle)
        self.timer.start(30)
        self.progress = 0
        
    def _progress_guncelle(self):
        self.progress += 2
        if self.progress >= 300:
            self.timer.stop()
            self.kapat()
            
        self.pixmap.fill(QColor("#0a1929"))
        painter = QPainter(self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Logo
        painter.setPen(QPen(QColor("#2196f3"), 3))
        painter.setBrush(QBrush(QColor("#1565c0")))
        painter.drawEllipse(350, 150, 100, 100)
        painter.setBrush(QBrush(QColor("#64b5f6")))
        painter.drawEllipse(375, 175, 20, 20)
        painter.drawEllipse(405, 175, 20, 20)
        
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 32, QFont.Weight.Bold))
        painter.drawText(self.pixmap.rect().adjusted(0, 100, 0, 0), 
                        Qt.AlignmentFlag.AlignCenter, "EYECONTROL OS")
        painter.setPen(QColor("#64b5f6"))
        painter.setFont(QFont("Segoe UI", 14))
        painter.drawText(self.pixmap.rect().adjusted(0, 180, 0, 0), 
                        Qt.AlignmentFlag.AlignCenter, "Hypervisor Kontrol Sistemi v2.0")
        
        # Progress
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#1e3a5f")))
        painter.drawRoundedRect(250, 450, 300, 6, 3, 3)
        painter.setBrush(QBrush(QColor("#2196f3")))
        painter.drawRoundedRect(250, 450, self.progress, 6, 3, 3)
        painter.end()
        self.setPixmap(self.pixmap)
        
    def kapat(self):
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(1000)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim.finished.connect(self.close)
        self.anim.start()

class GozYonuGostergesi(QGraphicsView):
    """Sağ alttaki gözün hangi tarafa baktığını gösteren koordinat sistemi"""
    def __init__(self):
        super().__init__()
        self.setFixedSize(180, 180)
        self.setStyleSheet("background-color: #1e3a5f; border: 2px solid #2196f3; border-radius: 8px;")
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        pen = QPen(QColor("#64b5f6"))
        pen.setWidth(2)
        self.scene.addLine(-70, 0, 70, 0, pen)
        self.scene.addLine(0, -70, 0, 70, pen)
        
        self.nokta = self.scene.addEllipse(-4, -4, 8, 8, 
                                          QPen(QColor("#2196f3")), 
                                          QBrush(QColor("#2196f3")))
        self.ok = self.scene.addLine(0, 0, 30, -30, QPen(QColor("#ff6b35"), 3))
        self.setSceneRect(-90, -90, 180, 180)
        
    def update_direction(self, x, y):
        self.scene.removeItem(self.ok)
        pen = QPen(QColor("#ff6b35"))
        pen.setWidth(3)
        self.ok = self.scene.addLine(0, 0, x * 0.6, -y * 0.6, pen)

class SanalKlavye(QWidget):
    """Büyük, gözle kontrol edilebilir QWERTY klavye"""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)
        
        satirlar = [
            ['1','2','3','4','5','6','7','8','9','0','-','='],
            ['Q','W','E','R','T','Y','U','I','O','P','[',']'],
            ['A','S','D','F','G','H','J','K','L',';','"', 'Enter'],
            ['Z','X','C','V','B','N','M',',','.','/','Shift'],
            ['Space']
        ]
        
        for satir in satirlar:
            h_layout = QHBoxLayout()
            h_layout.setSpacing(5)
            
            for tus in satir:
                btn = QPushButton(tus)
                btn.setMinimumHeight(45)  # Biraz daha kompakt
                
                if tus == 'Space':
                    btn.setMinimumWidth(400)
                    btn.setText("␣ Space")
                elif tus == 'Enter':
                    btn.setMinimumWidth(100)
                    btn.setStyleSheet("background-color: #4caf50;")
                elif tus == 'Shift':
                    btn.setMinimumWidth(100)
                    btn.setStyleSheet("background-color: #ff9800;")
                else:
                    btn.setMinimumWidth(55)
                
                btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                btn.setCheckable(True)
                btn.setObjectName("klavyeTus")
                h_layout.addWidget(btn)
                
            layout.addLayout(h_layout)
        layout.addStretch()

class CUAPanel(QWidget):
    """Yatay CUA butonları (Firefox, YouTube vb.)"""
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 10, 20, 10)  # Dikey margin azaltıldı
        
        self.butonlar = {}
        komutlar = [
            ("🌐 Firefox", "firefox"),
            ("▶️ YouTube", "youtube"),
            ("📁 Dosyalar", "files"),
            ("💻 Terminal", "terminal"),
            ("⚙️ Ayarlar", "settings"),
            ("❌ Kapat", "shutdown")
        ]
        
        for yazi, komut in komutlar:
            btn = QPushButton(yazi)
            btn.setMinimumHeight(60)  # Daha kompakt (eskiden 80)
            btn.setMinimumWidth(140)
            btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            btn.setCheckable(True)
            btn.setProperty("komut", komut)
            layout.addWidget(btn)
            self.butonlar[komut] = btn
            
        layout.addStretch()

class AnaPencere(QMainWindow):
    kamera_frame_geldi_sol = pyqtSignal(object)
    kamera_frame_geldi_sag = pyqtSignal(object)
    komut_calistir = pyqtSignal(str)
    klavye_tusuna_basildi = pyqtSignal(str)
    mod_degisti = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EyeControl OS - Hypervisor")
        self.setGeometry(100, 100, 1800, 1000)
        self.setMinimumSize(1600, 900)
        
        ana_widget = QWidget()
        self.setCentralWidget(ana_widget)
        
        # Ana yatay layout: Sol | Orta | Sağ
        ana_layout = QHBoxLayout(ana_widget)
        ana_layout.setSpacing(15)
        ana_layout.setContentsMargins(15, 15, 15, 15)
        
        # 1. SOL: Terminal
        self.sol_panel = self._olustur_terminal_panel()
        ana_layout.addWidget(self.sol_panel, 1)
        
        # 2. ORTA: QEMU + Dinamik Alt Panel
        self.orta_panel = self._olustur_orta_panel()
        ana_layout.addWidget(self.orta_panel, 5)  # Daha fazla yer ver
        
        # 3. SAĞ: Kameralar ve Kontroller
        self.sag_panel = self._olustur_sag_panel()
        ana_layout.addWidget(self.sag_panel, 1)
        
        self._tema_uygula()
        
        self.kamera_frame_geldi_sol.connect(self._kamera_sol_guncelle)
        self.kamera_frame_geldi_sag.connect(self._kamera_sag_guncelle)
        self.mod_degisti.connect(self._mod_degistir)
        
        self.aktif_mod = "klavye"
        
    def _olustur_terminal_panel(self):
        frame = QFrame()
        frame.setObjectName("terminalFrame")
        frame.setMinimumWidth(280)
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        
        baslik = QLabel("📋 Sistem Logları")
        baslik.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        baslik.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(baslik)
        
        self.log_alani = QTextEdit()
        self.log_alani.setObjectName("logText")
        self.log_alani.setReadOnly(True)
        self.log_alani.setFont(QFont("Consolas", 10))
        layout.addWidget(self.log_alani)
        
        return frame
    
    def _olustur_orta_panel(self):
        """Orta panel: QEMU (üst) + Dinamik Kontrol (alt)"""
        frame = QFrame()
        frame.setObjectName("ortaFrame")
        
        # Dikey splitter kullanarak boyutları ayarlayabilir veya 
        # basitçeVBoxLayout kullanarak stretch faktörleriyle oynayacağız
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # ÜST: QEMU Ekranı (Esnek, büyük alan)
        qemu_container = QWidget()
        qemu_layout = QVBoxLayout(qemu_container)
        qemu_layout.setContentsMargins(0, 0, 0, 0)
        
        qemu_baslik = QLabel("🖥️ QEMU Sanal Makine")
        qemu_baslik.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        qemu_layout.addWidget(qemu_baslik)
        
        self.qemu_ekran = QLabel()
        self.qemu_ekran.setObjectName("qemuEkran")
        self.qemu_ekran.setMinimumHeight(300)
        self.qemu_ekran.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qemu_ekran.setText("QEMU/VNC Bağlantısı Bekleniyor...")
        qemu_layout.addWidget(self.qemu_ekran, stretch=1)
        
        layout.addWidget(qemu_container, stretch=4)  # QEMU'ya daha çok yer
        
        # ALT: Dinamik Kontrol Alanı (Klavye veya CUA)
        self.kontrol_container = QFrame()
        self.kontrol_container.setObjectName("kontrolContainer")
        kontrol_layout = QVBoxLayout(self.kontrol_container)
        kontrol_layout.setContentsMargins(5, 5, 5, 5)
        kontrol_layout.setSpacing(0)
        
        # StackedWidget: Klavye ve CUA arasında geçiş yapar
        self.kontrol_stack = QStackedWidget()
        
        # Sayfa 0: Klavye (Büyük yer kaplar)
        self.klavye_widget = SanalKlavye()
        self.kontrol_stack.addWidget(self.klavye_widget)
        
        # Sayfa 1: CUA (Küçük yer kaplar)
        self.cua_widget = CUAPanel()
        self.kontrol_stack.addWidget(self.cua_widget)
        
        kontrol_layout.addWidget(self.kontrol_stack)
        layout.addWidget(self.kontrol_container, stretch=0)  # Başlangıçta 0, modda ayarlanacak
        
        return frame
    
    def _olustur_sag_panel(self):
        frame = QFrame()
        frame.setObjectName("sagFrame")
        frame.setMinimumWidth(320)
        frame.setMaximumWidth(400)
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Sol Göz Kamera
        kamera1_baslik = QLabel("👁️ Sol Göz Kamera")
        kamera1_baslik.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        layout.addWidget(kamera1_baslik)
        
        self.kamera1_label = QLabel()
        self.kamera1_label.setObjectName("kameraLabel")
        self.kamera1_label.setMinimumHeight(160)
        self.kamera1_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kamera1_label.setText("Kamera 1\nBağlantı Bekleniyor")
        layout.addWidget(self.kamera1_label)
        
        # Sağ Göz Kamera
        kamera2_baslik = QLabel("👁️ Sağ Göz Kamera")
        kamera2_baslik.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        layout.addWidget(kamera2_baslik)
        
        self.kamera2_label = QLabel()
        self.kamera2_label.setObjectName("kameraLabel")
        self.kamera2_label.setMinimumHeight(160)
        self.kamera2_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kamera2_label.setText("Kamera 2\nBağlantı Bekleniyor")
        layout.addWidget(self.kamera2_label)
        
        # Göz Yönü
        yon_baslik = QLabel("🎯 Bakış Yönü")
        yon_baslik.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        layout.addWidget(yon_baslik)
        
        self.goz_yonu = GozYonuGostergesi()
        layout.addWidget(self.goz_yonu, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Göz Durumu
        self.goz_durum = QLabel("● Gözler Açık")
        self.goz_durum.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.goz_durum.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.goz_durum.setStyleSheet("""
            color: #4caf50; 
            background-color: #0d47a1; 
            padding: 8px; 
            border-radius: 5px;
            border: 2px solid #2196f3;
        """)
        layout.addWidget(self.goz_durum)
        
        # MOD SEÇİM BUTONLARI - TAM İSİMLER
        mod_baslik = QLabel("🎮 Kontrol Modu")
        mod_baslik.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        layout.addWidget(mod_baslik)
        
        mod_layout = QHBoxLayout()
        mod_layout.setSpacing(8)
        
        # TAM İSİMLER: CUA, Klavye, Mouse
        self.btn_cua = QPushButton("🤖 CUA")
        self.btn_klavye = QPushButton("⌨️ Klavye")
        self.btn_mouse = QPushButton("🖱️ Mouse")
        
        for btn in [self.btn_cua, self.btn_klavye, self.btn_mouse]:
            btn.setCheckable(True)
            btn.setFixedHeight(45)
            btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            mod_layout.addWidget(btn)
        
        self.btn_cua.clicked.connect(lambda: self._mod_sec("cua"))
        self.btn_klavye.clicked.connect(lambda: self._mod_sec("klavye"))
        self.btn_mouse.clicked.connect(lambda: self._mod_sec("mouse"))
        
        layout.addLayout(mod_layout)
        layout.addStretch()
        
        return frame
    
    def _tema_uygula(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0a1929;
            }
            QWidget {
                font-family: "Segoe UI", "Roboto", sans-serif;
                color: #e3f2fd;
            }
            QFrame#terminalFrame, QFrame#sagFrame {
                background-color: #1e3a5f;
                border: 2px solid #2196f3;
                border-radius: 10px;
            }
            QFrame#ortaFrame {
                background-color: #0d47a1;
                border: 2px solid #2196f3;
                border-radius: 10px;
            }
            QFrame#kontrolContainer {
                background-color: #1565c0;
                border: 2px solid #2196f3;
                border-radius: 8px;
            }
            QLabel#qemuEkran {
                background-color: #1565c0;
                color: #e3f2fd;
                border: 2px solid #64b5f6;
                border-radius: 8px;
                font-size: 16px;
            }
            QLabel#kameraLabel {
                background-color: #0d47a1;
                color: #90caf9;
                border: 2px dashed #2196f3;
                border-radius: 8px;
            }
            QTextEdit#logText {
                background-color: #0a1929;
                color: #00e676;
                border: 1px solid #2196f3;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton {
                background-color: #1e3a5f;
                color: #e3f2fd;
                border: 2px solid #2196f3;
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2196f3;
                color: #0a1929;
            }
            QPushButton:checked {
                background-color: #2196f3;
                color: #0a1929;
                border-color: #64b5f6;
            }
            QPushButton#klavyeTus {
                background-color: #2d5a8f;
                border: 2px solid #64b5f6;
                font-size: 13px;
            }
            QPushButton#klavyeTus:hover {
                background-color: #42a5f5;
            }
            QPushButton#klavyeTus:checked {
                background-color: #ff6b35;
                color: white;
                border-color: #ff8a65;
            }
        """)
    
    def _mod_sec(self, mod):
        self.mod_degisti.emit(mod)
        self._mod_degistir(mod)
        
    def _mod_degistir(self, mod):
        """Mod değiştiğinde alt panelin boyutunu ve görünürlüğünü ayarla"""
        self.aktif_mod = mod
        
        # Buton durumlarını güncelle
        self.btn_cua.setChecked(mod == "cua")
        self.btn_klavye.setChecked(mod == "klavye")
        self.btn_mouse.setChecked(mod == "mouse")
        
        # MOUSE MODU: StackWidget'i tamamen gizle
        if mod == "mouse":
            self.kontrol_stack.setVisible(False)  # ← KRİTİK: İçeriği gizle
            self.kontrol_container.setMinimumHeight(40)   # Çok ince (sadece çerçeve)
            self.kontrol_container.setMaximumHeight(50)
            self._log_yaz("[MOD] Mouse modu (Göz tüm ekranda geziniyor)")
            
        # KLAVYE MODU: StackWidget'i göster, Klavye sayfasına geç
        elif mod == "klavye":
            self.kontrol_stack.setVisible(True)   # ← Göster
            self.kontrol_stack.setCurrentIndex(0) # ← Klavye sayfası (0. index)
            self.kontrol_container.setMinimumHeight(320)
            self.kontrol_container.setMaximumHeight(450)
            self._log_yaz("[MOD] Klavye moduna geçildi")
            
        # CUA MODU: StackWidget'i göster, CUA sayfasına geç  
        elif mod == "cua":
            self.kontrol_stack.setVisible(True)   # ← Göster
            self.kontrol_stack.setCurrentIndex(1) # ← CUA sayfası (1. index)
            self.kontrol_container.setMinimumHeight(100)
            self.kontrol_container.setMaximumHeight(130)
            self._log_yaz("[MOD] CUA moduna geçildi")
    
    def _kamera_sol_guncelle(self, frame):
        if isinstance(frame, QPixmap):
            self.kamera1_label.setPixmap(frame.scaled(
                self.kamera1_label.size(), 
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
    
    def _kamera_sag_guncelle(self, frame):
        if isinstance(frame, QPixmap):
            self.kamera2_label.setPixmap(frame.scaled(
                self.kamera2_label.size(), 
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
    
    def goz_yonu_guncelle(self, x, y):
        self.goz_yonu.update_direction(x, y)
    
    def goz_durum_guncelle(self, sol_acik, sag_acik):
        if sol_acik and sag_acik:
            self.goz_durum.setText("● Her İki Göz Açık")
            self.goz_durum.setStyleSheet("color: #4caf50; background-color: #0d47a1; padding: 8px; border-radius: 5px; border: 2px solid #2196f3;")
        elif sol_acik:
            self.goz_durum.setText("● Sol Göz Açık")
            self.goz_durum.setStyleSheet("color: #ff9800; background-color: #0d47a1; padding: 8px; border-radius: 5px; border: 2px solid #2196f3;")
        elif sag_acik:
            self.goz_durum.setText("● Sağ Göz Açık")
            self.goz_durum.setStyleSheet("color: #ff9800; background-color: #0d47a1; padding: 8px; border-radius: 5px; border: 2px solid #2196f3;")
        else:
            self.goz_durum.setText("● Gözler Kapalı")
            self.goz_durum.setStyleSheet("color: #f44336; background-color: #0d47a1; padding: 8px; border-radius: 5px; border: 2px solid #2196f3;")
    
    def _log_yaz(self, mesaj):
        from datetime import datetime
        zaman = datetime.now().strftime("%H:%M:%S")
        self.log_alani.append(f"[{zaman}] {mesaj}")
        scrollbar = self.log_alani.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def klavye_tus_vurgula(self, tus):
        for btn in self.klavye_widget.findChildren(QPushButton):
            if btn.text() == tus or (tus == " " and btn.text() == "␣ Space"):
                btn.setChecked(True)
            else:
                btn.setChecked(False)
    
    def klavye_tus_bas(self, tus):
        self.klavye_tusuna_basildi.emit(tus)
        self._log_yaz(f"[KLAVYE] '{tus}' tuşuna basıldı")
    
    def cua_buton_vurgula(self, komut):
        if komut in self.cua_widget.butonlar:
            for k, btn in self.cua_widget.butonlar.items():
                btn.setChecked(k == komut)
    
    def cua_buton_bas(self, komut):
        self.komut_calistir.emit(komut)
        self._log_yaz(f"[CUA] '{komut}' komutu çalıştırılıyor...")
    
    def qemu_ekran_guncelle(self, pixmap):
        self.qemu_ekran.setPixmap(pixmap.scaled(
            self.qemu_ekran.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0a1929"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e3f2fd"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1e3a5f"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e3f2fd"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1e3a5f"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e3f2fd"))
    app.setPalette(palette)
    
    splash = ProfesyonelSplash()
    splash.show()
    splash.animasyon_baslat()
    
    pencere = AnaPencere()
    QTimer.singleShot(3500, pencere.show)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()