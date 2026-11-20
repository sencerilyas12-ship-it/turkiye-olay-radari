
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DOSYA = Path("haberler.json")

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

KATEGORILER = {
    "Cinayet ve şüpheli ölüm": "cinayet OR öldürüldü OR şüpheli ölüm",
    "Kadın cinayetleri": "kadın cinayeti OR kadın öldürüldü",
    "Cinsel saldırı ve istismar": "cinsel saldırı OR cinsel istismar",
    "Çocuk istismarı": "çocuğa istismar OR çocuk istismarı",
    "Büyük çaplı dolandırıcılık": "dolandırıcılık OR sahte yatırım",
    "Kamu skandalları": "kamu skandalı OR kamu kurumu soruşturma",
    "Vatandaş mağduriyetleri": "vatandaş mağduriyeti OR vatandaş şikayet",
    "Yolsuzluk ve usulsüzlük": "yolsuzluk OR usulsüzlük OR rüşvet",
    "Adli soruşturmalar": "adli soruşturma OR savcılık soruşturması",
    "Duruşmalar ve kararlar": "mahkeme duruşma OR mahkeme kararı OR tutuklandı OR tahliye"
}


def rss_getir(il, kategori, arama):
    sorgu = f'"{il}" ({arama})'

    adres = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(sorgu)
        + "&hl=tr&gl=TR&ceid=TR:tr"
    )

    istek = urllib.request.Request(
        adres,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    try:
        with urllib.request.urlopen(istek, timeout=12) as cevap:
            icerik = cevap.read()

        return ET.fromstring(icerik)

    except (urllib.error.URLError, ET.ParseError, TimeoutError) as hata:
        print(f"Hata: {il} - {kategori}: {hata}")
        return None


def tarih_duzenle(deger):
    if not deger:
        return ""

    try:
        tarih = parsedate_to_datetime(deger)
        return tarih.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return deger


def haberleri_yukle():
    if not DOSYA.exists():
        return []

    try:
        with DOSYA.open("r", encoding="utf-8") as dosya:
            veri = json.load(dosya)
        return veri if isinstance(veri, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def ana():
    haberler = haberleri_yukle()
    mevcut_linkler = {
        haber.get("link")
        for haber in haberler
        if haber.get("link")
    }

    yeni_sayi = 0

    for il in ILLER:
        for kategori, arama in KATEGORILER.items():
            kok = rss_getir(il, kategori, arama)

            if kok is None:
                continue

            for oge in kok.findall("./channel/item"):
                baslik = oge.findtext("title", "").strip()
                link = oge.findtext("link", "").strip()
                tarih = oge.findtext("pubDate", "").strip()

                kaynak_oge = oge.find("source")
                kaynak = (
                    kaynak_oge.text.strip()
                    if kaynak_oge is not None and kaynak_oge.text
                    else "Bilinmeyen kaynak"
                )

                if not baslik or not link or link in mevcut_linkler:
                    continue

                haberler.append({
                    "il": il,
                    "kategori": kategori,
                    "baslik": baslik,
                    "link": link,
                    "kaynak": kaynak,
                    "tarih": tarih_duzenle(tarih),
                    "toplanma_tarihi": datetime.now(
                        timezone.utc
                    ).isoformat()
                })

                mevcut_linkler.add(link)
                yeni_sayi += 1

            print(f"{il} - {kategori} tamamlandı.")
            time.sleep(0.2)

    haberler.sort(
        key=lambda x: x.get("tarih", ""),
        reverse=True
    )

    with DOSYA.open("w", encoding="utf-8") as dosya:
        json.dump(
            haberler,
            dosya,
            ensure_ascii=False,
            indent=2
        )

    print("--------------------------------")
    print("HABER TOPLAMA TAMAMLANDI")
    print("Yeni haber:", yeni_sayi)
    print("Toplam haber:", len(haberler))
    print("--------------------------------")


if __name__ == "__main__":
    ana()
