
import json
import os
import re
import time
import hashlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KAYNAK_DOSYASI = os.path.join(BASE_DIR, "kaynaklar.json")
HABER_DOSYASI = os.path.join(BASE_DIR, "haberler.json")
DURUM_DOSYASI = os.path.join(BASE_DIR, "tarama_durumu.json")

USER_AGENT = "MIHVER-NewsMonitor/1.0 (public-interest news monitoring)"
MAX_HABER = 50000
MAX_RSS_KAYNAK = 80
MAX_GOOGLE_SORGU = 8
TIMEOUT = 20

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
    "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye", "Düzce"
]

KONULAR = [
    '"mahkeme" OR "duruşma" OR "adliye" OR "başsavcılık"',
    '"belediye" OR "ihale" OR "meclis kararı" OR "imar"',
    '"kamu görevlisi" OR "soruşturma" OR "denetim" OR "usulsüzlük"',
    '"vatandaş şikayeti" OR "yerel gündem" OR "basın açıklaması"'
]

HARIC_TERIMLER = [
    "uyuşturucu", "siber suç", "trafik kazası",
    "kayıp şahıs", "kayıp kişi"
]


def oku_json(dosya, varsayilan):
    try:
        with open(dosya, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return varsayilan


def yaz_json(dosya, veri):
    gecici = dosya + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)
    os.replace(gecici, dosya)


def indir(url):
    istek = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"
        }
    )
    with urllib.request.urlopen(istek, timeout=TIMEOUT) as cevap:
        return cevap.read()


def temizle(metin):
    metin = re.sub(r"<[^>]+>", " ", metin or "")
    metin = re.sub(r"\s+", " ", metin)
    return metin.strip()


def tarih_duzenle(deger):
    if not deger:
        return datetime.now(timezone.utc).isoformat()

    try:
        tarih = parsedate_to_datetime(deger)
        return tarih.astimezone(timezone.utc).isoformat()
    except Exception:
        pass

    try:
        tarih = datetime.fromisoformat(deger.replace("Z", "+00:00"))
        return tarih.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def haber_kimligi(link, baslik):
    veri = (link or baslik).strip().lower()
    return hashlib.sha256(veri.encode("utf-8")).hexdigest()


def uygun_haber(baslik, aciklama):
    metin = (baslik + " " + aciklama).lower()

    if len(baslik.strip()) < 12:
        return False

    if any(terim in metin for terim in HARIC_TERIMLER):
        return False

    return True


def rss_oku(url, il, kaynak_adi, kaynak_durumu):
    bulunanlar = []

    try:
        icerik = indir(url)
        kok = ET.fromstring(icerik)

        for item in kok.findall(".//item"):
            baslik = temizle(item.findtext("title", ""))
            link = temizle(item.findtext("link", ""))
            aciklama = temizle(item.findtext("description", ""))
            tarih = item.findtext("pubDate", "")

            if not baslik or not link or not uygun_haber(baslik, aciklama):
                continue

            bulunanlar.append({
                "baslik": baslik,
                "il": il or "Türkiye",
                "kategori": "Yerel Gündem",
                "kaynak": kaynak_adi,
                "tarih": tarih_duzenle(tarih),
                "link": link,
                "durum": "aday" if kaynak_durumu != "doğrulandı" else "doğrulandı",
                "kimlik": haber_kimligi(link, baslik)
            })

        ns = {"a": "http://www.w3.org/2005/Atom"}

        for entry in kok.findall(".//a:entry", ns):
            baslik = temizle(entry.findtext("a:title", "", ns))
            aciklama = temizle(entry.findtext("a:summary", "", ns))
            tarih = entry.findtext("a:updated", "", ns)
            link_elemani = entry.find("a:link", ns)
            link = link_elemani.attrib.get("href", "") if link_elemani is not None else ""

            if not baslik or not link or not uygun_haber(baslik, aciklama):
                continue

            bulunanlar.append({
                "baslik": baslik,
                "il": il or "Türkiye",
                "kategori": "Yerel Gündem",
                "kaynak": kaynak_adi,
                "tarih": tarih_duzenle(tarih),
                "link": link,
                "durum": "aday" if kaynak_durumu != "doğrulandı" else "doğrulandı",
                "kimlik": haber_kimligi(link, baslik)
            })

    except Exception as hata:
        print("RSS okunamadı:", url, str(hata)[:180])

    return bulunanlar


def google_haber_rss(il, konu):
    sorgu = f"{il} {konu}"
    parametre = urllib.parse.urlencode({
        "q": sorgu,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr"
    })
    return "https://news.google.com/rss/search?" + parametre


def google_ara(il, konu):
    url = google_haber_rss(il, konu)
    return rss_oku(url, il, "Google Haberler RSS", "aday")


def ana_islem():
    kaynaklar = oku_json(KAYNAK_DOSYASI, [])
    haberler = oku_json(HABER_DOSYASI, [])
    durum = oku_json(DURUM_DOSYASI, {"arama_sirasi": 0})

    if not isinstance(kaynaklar, list):
        kaynaklar = []

    if not isinstance(haberler, list):
        haberler = []

    kimlikler = set()
    for haber in haberler:
        if isinstance(haber, dict):
            kimlik = haber.get("kimlik") or haber_kimligi(
                haber.get("link", ""),
                haber.get("baslik", "")
            )
            kimlikler.add(kimlik)

    yeni_haberler = []

    rss_kaynaklari = [
        kaynak for kaynak in kaynaklar
        if isinstance(kaynak, dict) and kaynak.get("rss")
    ][:MAX_RSS_KAYNAK]

    for kaynak in rss_kaynaklari:
        url = kaynak.get("rss", "").strip()
        if not url.startswith("https://"):
            continue

        sonuc = rss_oku(
            url,
            kaynak.get("il", "Türkiye"),
            kaynak.get("ad", kaynak.get("isim", "Yerel kaynak")),
            kaynak.get("durum", "aday")
        )
        yeni_haberler.extend(sonuc)

    toplam_sorgu = len(ILLER) * len(KONULAR)
    baslangic = int(durum.get("arama_sirasi", 0)) % toplam_sorgu

    for i in range(MAX_GOOGLE_SORGU):
        sira = (baslangic + i) % toplam_sorgu
        il_index = sira // len(KONULAR)
        konu_index = sira % len(KONULAR)

        il = ILLER[il_index]
        konu = KONULAR[konu_index]

        print("Şehir/konu taranıyor:", il, konu)
        yeni_haberler.extend(google_ara(il, konu))
        time.sleep(1)

    eklenen = 0

    for haber in yeni_haberler:
        kimlik = haber.get("kimlik")

        if not kimlik or kimlik in kimlikler:
            continue

        haberler.append(haber)
        kimlikler.add(kimlik)
        eklenen += 1

    haberler.sort(
        key=lambda x: x.get("tarih", ""),
        reverse=True
    )

    haberler = haberler[:MAX_HABER]

    durum["arama_sirasi"] = (baslangic + MAX_GOOGLE_SORGU) % toplam_sorgu
    durum["son_calisma"] = datetime.now(timezone.utc).isoformat()
    durum["son_eklenen_haber"] = eklenen

    yaz_json(HABER_DOSYASI, haberler)
    yaz_json(DURUM_DOSYASI, durum)

    print("Tarama tamamlandı.")
    print("RSS kaynak sayısı:", len(rss_kaynaklari))
    print("Yeni haber sayısı:", eklenen)
    print("Toplam haber sayısı:", len(haberler))


if __name__ == "__main__":
    ana_islem()
