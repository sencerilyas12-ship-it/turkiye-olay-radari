
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime


BASE_DIR = Path(__file__).resolve().parent
HABER_DOSYASI = BASE_DIR / "haberler.json"
DURUM_DOSYASI = BASE_DIR / "tarama_durumu.json"

USER_AGENT = "MIHVER-TurkiyeHaberRadar/5.0"
TIMEOUT = 12
HABER_SURESI_SAAT = 24

# Her çalışmada sınırlı sayıda sorgu yapılır.
# GitHub Actions 5 dakikada bir çalıştığı için tarama
# zaman içinde bütün illere ve kategorilere yayılır.
MAKS_SORGU = 80
BEKLEME = 0.15

ILLER = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya",
    "Ankara", "Antalya", "Artvin", "Aydın", "Balıkesir",
    "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur",
    "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli",
    "Diyarbakır", "Edirne", "Elazığ", "Erzincan", "Erzurum",
    "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari",
    "Hatay", "Isparta", "Mersin", "İstanbul", "İzmir",
    "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir",
    "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa",
    "Kahramanmaraş", "Mardin", "Muğla", "Muş", "Nevşehir",
    "Niğde", "Ordu", "Rize", "Sakarya", "Samsun",
    "Siirt", "Sinop", "Sivas", "Tekirdağ", "Tokat",
    "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van",
    "Yozgat", "Zonguldak", "Aksaray", "Bayburt", "Karaman",
    "Kırıkkale", "Batman", "Şırnak", "Bartın", "Ardahan",
    "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye",
    "Düzce"
]

# Genel haber kategorileri
KATEGORILER = {
    "Gündem": "Türkiye gündem son dakika",
    "Asayiş": "asayiş polis jandarma operasyon",
    "Cinayet": "cinayet öldürüldü şüpheli ölüm",
    "Kadın cinayetleri": "kadın cinayeti kadın öldürüldü",
    "Çocuk haberleri": "çocuk haberleri çocuk istismarı",
    "Adliye": "adliye mahkeme duruşma savcılık",
    "Soruşturma": "soruşturma gözaltı tutuklama tahliye",
    "Ekonomi": "ekonomi enflasyon döviz faiz piyasa",
    "İş dünyası": "şirketler iş dünyası yatırım",
    "Belediye": "belediye meclisi yerel yönetim",
    "Siyaset": "siyaset açıklama parti hükümet",
    "Eğitim": "eğitim okul üniversite öğretmen",
    "Sağlık": "sağlık hastane doktor sağlık sistemi",
    "Spor": "spor futbol basketbol transfer",
    "Teknoloji": "teknoloji bilim yapay zeka",
    "Kültür sanat": "kültür sanat sinema tiyatro",
    "Ulaşım": "ulaşım metro otobüs tren uçak",
    "Trafik kazaları": "trafik kazası yaralı hayatını kaybetti",
    "Doğal afet": "deprem sel yangın fırtına",
    "Uyuşturucu": "uyuşturucu operasyonu ele geçirildi",
    "Dolandırıcılık": "dolandırıcılık sahte yatırım",
    "Yolsuzluk": "yolsuzluk rüşvet usulsüzlük",
    "Çevre": "çevre kirliliği orman çevre",
    "Tarım": "tarım çiftçi hayvancılık",
    "Turizm": "turizm otel tatil",
    "Dış haberler": "dünya son dakika uluslararası",
    "Savunma": "savunma sanayi askeri güvenlik",
    "Çalışma hayatı": "işçi emekli asgari ücret",
    "Vatandaş": "vatandaş mağduriyet şikayet"
}

def simdi():
    return datetime.now(timezone.utc)


def tarih_coz(deger):
    if not deger:
        return None

    try:
        tarih = parsedate_to_datetime(deger)

        if tarih.tzinfo is None:
            tarih = tarih.replace(tzinfo=timezone.utc)

        return tarih.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def tarih_iso(deger):
    tarih = tarih_coz(deger)

    if tarih is None:
        return ""

    return tarih.isoformat()


def haberleri_yukle():
    if not HABER_DOSYASI.exists():
        return []

    try:
        with HABER_DOSYASI.open("r", encoding="utf-8") as dosya:
            veri = json.load(dosya)

        if isinstance(veri, list):
            return veri

    except (OSError, json.JSONDecodeError) as hata:
        print("Haber dosyası okunamadı:", hata)

    return []


def durumu_yukle():
    if not DURUM_DOSYASI.exists():
        return {}

    try:
        with DURUM_DOSYASI.open("r", encoding="utf-8") as dosya:
            veri = json.load(dosya)

        return veri if isinstance(veri, dict) else {}

    except (OSError, json.JSONDecodeError):
        return {}


def json_kaydet(dosya_yolu, veri):
    gecici = dosya_yolu.with_suffix(".tmp")

    with gecici.open("w", encoding="utf-8") as dosya:
        json.dump(veri, dosya, ensure_ascii=False, indent=2)

    gecici.replace(dosya_yolu)


def eski_haberleri_temizle(haberler):
    sinir = simdi() - timedelta(hours=HABER_SURESI_SAAT)
    temiz = []

    for haber in haberler:
        tarih = tarih_coz(haber.get("tarih", ""))

        if tarih is None:
            toplanma = tarih_coz(haber.get("toplanma_tarihi", ""))
            tarih = toplanma

        if tarih and tarih >= sinir:
            temiz.append(haber)

    return temiz


def rss_getir(il, kategori, arama):
    if il == "Türkiye":
        sorgu = arama
    else:
        sorgu = f'"{il}" ({arama})'

    adres = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(sorgu)
        + "&hl=tr&gl=TR&ceid=TR:tr"
    )

    istek = urllib.request.Request(
        adres,
        headers={"User-Agent": USER_AGENT}
    )

    try:
        with urllib.request.urlopen(istek, timeout=TIMEOUT) as cevap:
            icerik = cevap.read()

        return ET.fromstring(icerik)

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        ET.ParseError,
        TimeoutError,
        OSError
    ) as hata:
        print(f"RSS hatası: {il} / {kategori}: {hata}")
        return None


def rss_haberlerini_oku(kok, il, kategori):
    bulunan = []

    if kok is None:
        return bulunan

    for oge in kok.findall("./channel/item"):
        baslik = oge.findtext("title", "").strip()
        link = oge.findtext("link", "").strip()
        pub_date = oge.findtext("pubDate", "").strip()

        if not baslik or not link:
            continue

        tarih = tarih_coz(pub_date)

        # Tarihi okunamayan haberleri yanlışlıkla güncel
        # kabul etmiyoruz.
        if tarih is None:
            continue

        if tarih < simdi() - timedelta(hours=HABER_SURESI_SAAT):
            continue

        kaynak_oge = oge.find("source")

        if kaynak_oge is not None and kaynak_oge.text:
            kaynak = kaynak_oge.text.strip()
        else:
            kaynak = "Google Haberler"

        bulunan.append({
            "il": il,
            "kategori": kategori,
            "baslik": baslik,
            "link": link,
            "kaynak": kaynak,
            "tarih": tarih.isoformat(),
            "toplanma_tarihi": simdi().isoformat()
        })

    return bulunan


def sorgulari_olustur():
    sorgular = []

    # Önce Türkiye genelindeki haberleri tara.
    for kategori, arama in KATEGORILER.items():
        sorgular.append(("Türkiye", kategori, arama))

    # Ardından bütün illeri bütün kategorilerle tara.
    for il in ILLER:
        for kategori, arama in KATEGORILER.items():
            sorgular.append((il, kategori, arama))

    return sorgular


def ana():
    baslangic = time.time()

    haberler = haberleri_yukle()
    haberler = eski_haberleri_temizle(haberler)

    mevcut_linkler = {
        haber.get("link")
        for haber in haberler
        if haber.get("link")
    }

    durum = durumu_yukle()

    sorgular = sorgulari_olustur()
    toplam_sorgu = len(sorgular)

    # Her çalışmada kaldığı yerden devam eder.
    imlec = int(durum.get("sorgu_imleci", 0))
    imlec = imlec % toplam_sorgu

    secilenler = []

    for i in range(min(MAKS_SORGU, toplam_sorgu)):
        indeks = (imlec + i) % toplam_sorgu
        secilenler.append(sorgular[indeks])

    yeni_sayi = 0
    basarili_sorgu = 0
    hatali_sorgu = 0

    for sira, (il, kategori, arama) in enumerate(secilenler, start=1):
        kok = rss_getir(il, kategori, arama)

        if kok is None:
            hatali_sorgu += 1
            continue

        basarili_sorgu += 1

        yeni_haberler = rss_haberlerini_oku(
            kok,
            il,
            kategori
        )

        for haber in yeni_haberler:
            link = haber["link"]

            if link in mevcut_linkler:
                continue

            haberler.append(haber)
            mevcut_linkler.add(link)
            yeni_sayi += 1

        print(
            f"[{sira}/{len(secilenler)}] "
            f"{il} - {kategori} tamamlandı."
        )

        time.sleep(BEKLEME)

    # Sonraki çalışmanın başlayacağı sorgu.
    durum["sorgu_imleci"] = (
        imlec + len(secilenler)
    ) % toplam_sorgu

    durum["son_tarama"] = simdi().isoformat()
    durum["son_kaynak_kesfi"] = durum.get(
        "son_kaynak_kesfi",
        ""
    )

    # 24 saatten eski haberleri tekrar temizle.
    haberler = eski_haberleri_temizle(haberler)

    haberler.sort(
        key=lambda haber: haber.get("tarih", ""),
        reverse=True
    )

    json_kaydet(HABER_DOSYASI, haberler)
    json_kaydet(DURUM_DOSYASI, durum)

    sure = round(time.time() - baslangic, 2)

    print("")
    print("================================")
    print("MİHVER TÜRKİYE HABER RADARI")
    print("================================")
    print("Toplam il:", len(ILLER))
    print("Haber kategorisi:", len(KATEGORILER))
    print("Toplam tarama sorgusu:", toplam_sorgu)
    print("Bu çalışmadaki sorgu:", len(secilenler))
    print("Başarılı sorgu:", basarili_sorgu)
    print("Hatalı sorgu:", hatali_sorgu)
    print("Yeni haber:", yeni_sayi)
    print("24 saatlik arşiv:", len(haberler))
    print("Çalışma süresi:", sure, "saniye")
    print("================================")


if __name__ == "__main__":
    ana()
