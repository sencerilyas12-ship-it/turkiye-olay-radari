
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

DOSYA = Path("kaynaklar.json")

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

ARAMALAR = [
    "yerel haber",
    "adliye mahkeme duruşma"
]


def kaynaklari_yukle():
    if not DOSYA.exists():
        return {"iller": [], "kaynaklar": []}

    with DOSYA.open("r", encoding="utf-8") as dosya:
        veri = json.load(dosya)

    if not isinstance(veri, dict):
        raise ValueError("kaynaklar.json biçimi hatalı.")

    veri.setdefault("iller", [])
    veri.setdefault("kaynaklar", [])

    if not isinstance(veri["kaynaklar"], list):
        raise ValueError("Kaynak listesi hatalı.")

    return veri


def rss_getir(il, arama):
    sorgu = f'"{il}" {arama}'

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
        with urllib.request.urlopen(istek, timeout=20) as cevap:
            icerik = cevap.read()

        return ET.fromstring(icerik)

    except (urllib.error.URLError, ET.ParseError, TimeoutError) as hata:
        print(f"RSS hatası ({il}): {hata}")
        return None


def kaynaklari_bul(veri, il, arama):
    kok = rss_getir(il, arama)

    if kok is None:
        return 0

    eklenen = 0

    for oge in kok.findall("./channel/item"):
        kaynak = oge.find("source")

        if kaynak is None:
            continue

        ad = (kaynak.text or "").strip()
        url = kaynak.attrib.get("url", "").strip()

        if not ad or not url:
            continue

        if urlparse(url).scheme not in ("http", "https"):
            continue

        alan = urlparse(url).netloc.lower()

        if not alan:
            continue

        mevcut = any(
            kayit.get("alan") == alan
            for kayit in veri["kaynaklar"]
        )

        if mevcut:
            continue

        veri["kaynaklar"].append({
            "il": il,
            "ad": ad,
            "url": url,
            "alan": alan,
            "tur": "Google Haberler RSS",
            "durum": "aday",
            "arama": arama
        })

        eklenen += 1

    return eklenen


def ana():
    veri = kaynaklari_yukle()
    veri["iller"] = ILLER

    toplam = 0

    for il in ILLER:
        for arama in ARAMALAR:
            bulunan = kaynaklari_bul(veri, il, arama)
            toplam += bulunan

            print(
                f"{il} - {arama}: "
                f"{bulunan} yeni aday kaynak"
            )

            time.sleep(1)

    with DOSYA.open("w", encoding="utf-8") as dosya:
        json.dump(
            veri,
            dosya,
            ensure_ascii=False,
            indent=2
        )

    print("--------------------------------")
    print("KAYNAK ARAMASI TAMAMLANDI")
    print("İl sayısı:", len(ILLER))
    print("Yeni aday kaynak:", toplam)
    print("Toplam kayıt:", len(veri["kaynaklar"]))
    print("--------------------------------")


if __name__ == "__main__":
    ana()
