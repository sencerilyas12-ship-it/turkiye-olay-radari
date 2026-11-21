
import os
import re
import json
import time
import hashlib
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))

ENVANTER_DOSYASI = os.path.join(BASE, "kaynaklar_ek.json")
ESKI_KAYNAK_DOSYASI = os.path.join(BASE, "kaynaklar.json")
HABER_DOSYASI = os.path.join(BASE, "haberler.json")
DURUM_DOSYASI = os.path.join(BASE, "tarama_durumu.json")

USER_AGENT = "MIHVER-NewsMonitor/1.1"
TIMEOUT = 20

MAX_HABER = 50000
MAX_RSS_KAYNAK = 150
MAX_GOOGLE_SORGU = 12
MAX_HABER_KAYNAK_BASI = 30

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
    '"vatandaş şikayeti" OR "yerel gündem" OR "basın açıklaması"',
    '"tutuklama" OR "gözaltı" OR "mahkeme kararı"',
    '"kamu zararı" OR "yolsuzluk iddiası" OR "kamu ihalesi"'
]

HARIC_TERIMLER = [
    "uyuşturucu", "siber suç", "trafik kazası",
    "kayıp şahıs", "kayıp kişi"
]


def oku_json(dosya, varsayilan):
    try:
        with open(dosya, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return varsayilan
    except json.JSONDecodeError as hata:
        raise RuntimeError(f"{dosya} bozuk JSON içeriyor: {hata}")


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
    metin = unescape(metin or "")
    metin = re.sub(r"<[^>]+>", " ", metin)
    metin = re.sub(r"\s+", " ", metin)
    return metin.strip()


def tarih_duzenle(deger):
    if not deger:
        return datetime.now(timezone.utc).isoformat()

    try:
        tarih = parsedate_to_datetime(deger)
        if tarih.tzinfo is None:
            tarih = tarih.replace(tzinfo=timezone.utc)
        return tarih.astimezone(timezone.utc).isoformat()
    except Exception:
        pass

    try:
        tarih = datetime.fromisoformat(deger.replace("Z", "+00:00"))
        if tarih.tzinfo is None:
            tarih = tarih.replace(tzinfo=timezone.utc)
        return tarih.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def haber_kimligi(link, baslik):
    veri = (link or baslik).strip().lower()
    return hashlib.sha256(veri.encode("utf-8")).hexdigest()


def robots_izinli(url):
    try:
        parca = urlparse(url)
        robots_url = f"{parca.scheme}://{parca.netloc}/robots.txt"

        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(robots_url)
        robot.read()

        return robot.can_fetch(USER_AGENT, url)
    except Exception:
        # robots.txt okunamıyorsa temkinli davran.
        return False


def uygun_haber(baslik, aciklama):
    metin = (baslik + " " + aciklama).lower()

    if len(baslik.strip()) < 12:
        return False

    if any(terim in metin for terim in HARIC_TERIMLER):
        return False

    return True


def google_haber_rss(il, konu):
    sorgu = f'"{il}" {konu}'
    parametre = urllib.parse.urlencode({
        "q": sorgu,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr"
    })
    return "https://news.google.com/rss/search?" + parametre


def kategori_belirle(baslik, aciklama):
    metin = (baslik + " " + aciklama).lower()

    if any(x in metin for x in ["duruşma", "mahkeme", "karar açıklandı"]):
        return "Mahkeme ve Duruşma"
    if any(x in metin for x in ["belediye", "meclis", "imar"]):
        return "Yerel Yönetim"
    if any(x in metin for x in ["ihale", "kamu zararı", "yolsuzluk"]):
        return "Kamu ve İhale"
    if any(x in metin for x in ["tutuklama", "gözaltı", "başsavcılık"]):
        return "Adli Gelişmeler"
    if any(x in metin for x in ["cinayet", "şüpheli ölüm"]):
        return "Asayiş ve Adli Olaylar"

    return "Yerel Gündem"


def haber_kaydi(baslik, link, aciklama, tarih, il, kaynak_adi, kaynak_durumu):
    return {
        "baslik": baslik,
        "aciklama": aciklama[:1200],
        "il": il or "Türkiye",
        "kategori": kategori_belirle(baslik, aciklama),
        "kaynak": kaynak_adi,
        "tarih": tarih_duzenle(tarih),
        "link": link,
        "durum": "doğrulanmadı" if kaynak_durumu != "doğrulandı" else "doğrulandı",
        "yayinda": True,
        "kimlik": haber_kimligi(link, baslik)
    }


def rss_oku(url, il, kaynak_adi, kaynak_durumu, robots_kontrol=True):
    bulunanlar = []

    if not url.startswith(("https://", "http://")):
        return bulunanlar

    if robots_kontrol and not robots_izinli(url):
        print("Robots.txt izni yok veya kontrol edilemedi:", url)
        return bulunanlar

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

            bulunanlar.append(
                haber_kaydi(
                    baslik, link, aciklama, tarih,
                    il, kaynak_adi, kaynak_durumu
                )
            )

        ns = {"a": "http://www.w3.org/2005/Atom"}

        for entry in kok.findall(".//a:entry", ns):
            baslik = temizle(entry.findtext("a:title", "", ns))
            aciklama = temizle(entry.findtext("a:summary", "", ns))
            tarih = entry.findtext("a:updated", "", ns)
            link_elemani = entry.find("a:link", ns)
            link = (
                link_elemani.attrib.get("href", "")
                if link_elemani is not None else ""
            )

            if not baslik or not link or not uygun_haber(baslik, aciklama):
                continue

            bulunanlar.append(
                haber_kaydi(
                    baslik, link, aciklama, tarih,
                    il, kaynak_adi, kaynak_durumu
                )
            )

    except Exception as hata:
        print("RSS okunamadı:", url, str(hata)[:180])

    return bulunanlar[:MAX_HABER_KAYNAK_BASI]


def kaynaklari_birlestir(eski_kaynaklar, ek_envanter):
    sonuc = []

    for kaynak in eski_kaynaklar:
        if isinstance(kaynak, dict):
            sonuc.append(kaynak)

    for kaynak in ek_envanter.get("kaynaklar", []):
        if not isinstance(kaynak, dict):
            continue

        rss = kaynak.get("rss") or kaynak.get("rss_url") or ""
        if not rss:
            continue

        sonuc.append({
            "id": kaynak.get("id"),
            "ad": kaynak.get("ad") or kaynak.get("isim") or "Ek kaynak",
            "il": kaynak.get("il") or "Türkiye",
            "rss": rss,
            "durum": kaynak.get("durum", "aday"),
            "kaynak_durumu": kaynak.get("dogrulama", "doğrulanmadı")
        })

    return sonuc


def ana_islem():
    envanter = oku_json(ENVANTER_DOSYASI, {})
    eski_kaynaklar = oku_json(ESKI_KAYNAK_DOSYASI, [])
    haberler = oku_json(HABER_DOSYASI, [])
    durum = oku_json(DURUM_DOSYASI, {"arama_sirasi": 0})

    if not isinstance(envanter, dict):
        raise RuntimeError("kaynaklar_ek.json biçimi hatalı.")

    if not isinstance(eski_kaynaklar, list):
        eski_kaynaklar = []

    if not isinstance(haberler, list):
        raise RuntimeError("haberler.json liste biçiminde değil; dosya korunarak işlem durduruldu.")

    ayarlar = envanter.get("ayarlar", {})
    yayin_ayarlari = envanter.get("haber_toplama_kapsami", {})
    dogrulama = envanter.get("dogrulama_kurallari", {})

    otomatik_yayin = (
        ayarlar.get("haberleri_otomatik_yayinla", False)
        and yayin_ayarlari.get("otomatik_yayin", False)
        and yayin_ayarlari.get("dogrulanmamis_haber_yayini", False)
    )

    robots_kontrol = dogrulama.get("robots_txt_kontrolu", True)

    kaynaklar = kaynaklari_birlestir(eski_kaynaklar, envanter)

    rss_kaynaklari = [
        kaynak for kaynak in kaynaklar
        if kaynak.get("rss")
    ][:MAX_RSS_KAYNAK]

    kimlikler = set()
    for haber in haberler:
        if isinstance(haber, dict):
            kimlik = haber.get("kimlik") or haber_kimligi(
                haber.get("link", ""),
                haber.get("baslik", "")
            )
            kimlikler.add(kimlik)

    yeni_haberler = []

    for kaynak in rss_kaynaklari:
        url = str(kaynak.get("rss", "")).strip()
        if not url:
            continue

        sonuc = rss_oku(
            url,
            kaynak.get("il", "Türkiye"),
            kaynak.get("ad", "Yerel kaynak"),
            kaynak.get("kaynak_durumu", kaynak.get("durum", "doğrulanmadı")),
            robots_kontrol
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

        url = google_haber_rss(il, konu)
        sonuc = rss_oku(
            url,
            il,
            "Google Haberler RSS",
            "doğrulanmadı",
            robots_kontrol=False
        )
        yeni_haberler.extend(sonuc)
        time.sleep(1)

    eklenen = 0

    for haber in yeni_haberler:
        kimlik = haber.get("kimlik")

        if not kimlik or kimlik in kimlikler:
            continue

        haber["yayinda"] = bool(otomatik_yayin)
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
    durum["toplam_haber"] = len(haberler)
    durum["rss_kaynak_sayisi"] = len(rss_kaynaklari)
    durum["otomatik_yayin"] = otomatik_yayin

    yaz_json(HABER_DOSYASI, haberler)
    yaz_json(DURUM_DOSYASI, durum)

    print("MİHVER taraması tamamlandı.")
    print("RSS kaynak sayısı:", len(rss_kaynaklari))
    print("Yeni haber sayısı:", eklenen)
    print("Toplam haber sayısı:", len(haberler))
    print("Otomatik yayın:", otomatik_yayin)


if __name__ == "__main__":
    ana_islem()
