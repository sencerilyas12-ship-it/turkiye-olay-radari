
import os
import re
import json
import time
import hashlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

BASE = os.path.dirname(os.path.abspath(__file__))

DOSYALAR = {
    "envanter": os.path.join(BASE, "kaynaklar_ek.json"),
    "kaynaklar": os.path.join(BASE, "kaynaklar.json"),
    "haberler": os.path.join(BASE, "haberler.json"),
    "durum": os.path.join(BASE, "tarama_durumu.json"),
    "ilceler": os.path.join(BASE, "ilceler.json"),
}

USER_AGENT = "MIHVER-NewsMonitor/2.0"
TIMEOUT = 20

# Her çalışmada taranacak ilçe-konu sorgusu
MAX_SORGU = 300

# İstekler arasında kısa bekleme
BEKLEME = 0.25

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


def oku(dosya, varsayilan):
    try:
        with open(dosya, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return varsayilan
    except json.JSONDecodeError as hata:
        raise RuntimeError(f"JSON hatası: {dosya}: {hata}")


def yaz(dosya, veri):
    gecici = dosya + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)
    os.replace(gecici, dosya)


def indir(url):
    istek = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml"
        }
    )
    with urllib.request.urlopen(istek, timeout=TIMEOUT) as cevap:
        return cevap.read()


def temizle(metin):
    metin = unescape(metin or "")
    metin = re.sub(r"<[^>]+>", " ", metin)
    return re.sub(r"\s+", " ", metin).strip()


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


def kimlik(link, baslik):
    veri = (link or baslik).strip().lower()
    return hashlib.sha256(veri.encode("utf-8")).hexdigest()


def kategori(baslik, aciklama):
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


def uygun(baslik, aciklama):
    metin = (baslik + " " + aciklama).lower()
    return (
        len(baslik.strip()) >= 12
        and not any(x in metin for x in HARIC_TERIMLER)
    )


def ilceleri_yukle():
    veri = oku(DOSYALAR["ilceler"], None)

    if not isinstance(veri, dict):
        raise RuntimeError("ilceler.json okunamadı.")

    sehirler = veri.get("cities", [])
    ilceler = veri.get("districts", [])

    sehir_esleme = {}

    for sehir in sehirler:
        try:
            sehir_esleme[int(sehir["Id"])] = str(
                sehir["name"]
            ).strip()
        except (KeyError, TypeError, ValueError):
            continue

    sonuc = []
    gorulen = set()

    for kayit in ilceler:
        try:
            il = sehir_esleme[int(kayit["cityId"])]
            ilce = str(kayit["name"]).strip()
        except (KeyError, TypeError, ValueError):
            continue

        anahtar = (il.casefold(), ilce.casefold())

        if ilce and anahtar not in gorulen:
            sonuc.append({"il": il, "ilce": ilce})
            gorulen.add(anahtar)

    if not sonuc:
        raise RuntimeError("İlçe listesi boş.")

    print("Şehir sayısı:", len(sehir_esleme))
    print("Okunan benzersiz ilçe sayısı:", len(sonuc))

    if len(sonuc) != 922:
        print("UYARI: İlçe listesi 922 değil:", len(sonuc))

    return sonuc


def google_url(il, ilce, konu):
    sorgu = f'"{ilce}" "{il}" {konu}'

    parametre = urllib.parse.urlencode({
        "q": sorgu,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr"
    })

    return "https://news.google.com/rss/search?" + parametre


def haber_olustur(baslik, link, aciklama, tarih, il, ilce, kaynak):
    return {
        "baslik": baslik,
        "aciklama": aciklama[:1200],
        "il": il,
        "ilce": ilce,
        "kategori": kategori(baslik, aciklama),
        "kaynak": kaynak,
        "tarih": tarih_duzenle(tarih),
        "link": link,
        "durum": "doğrulanmadı",
        "yayinda": True,
        "kimlik": kimlik(link, baslik)
    }


def rss_oku(url, il, ilce, kaynak):
    bulunan = []

    try:
        kok = ET.fromstring(indir(url))

        for item in kok.findall(".//item"):
            baslik = temizle(item.findtext("title", ""))
            link = temizle(item.findtext("link", ""))
            aciklama = temizle(item.findtext("description", ""))
            tarih = item.findtext("pubDate", "")

            if not baslik or not link or not uygun(baslik, aciklama):
                continue

            bulunan.append(
                haber_olustur(
                    baslik, link, aciklama, tarih,
                    il, ilce, kaynak
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

            if not baslik or not link or not uygun(baslik, aciklama):
                continue

            bulunan.append(
                haber_olustur(
                    baslik, link, aciklama, tarih,
                    il, ilce, kaynak
                )
            )

    except Exception as hata:
        print("RSS okunamadı:", str(hata)[:160])

    return bulunan


def kaynaklari_yukle(envanter):
    eski = oku(DOSYALAR["kaynaklar"], [])

    if not isinstance(eski, list):
        eski = []

    sonuc = []

    for kaynak in eski:
        if isinstance(kaynak, dict) and kaynak.get("rss"):
            sonuc.append(kaynak)

    for kaynak in envanter.get("kaynaklar", []):
        if not isinstance(kaynak, dict):
            continue

        rss = kaynak.get("rss") or kaynak.get("rss_url")

        if rss:
            sonuc.append({
                "ad": kaynak.get("ad") or kaynak.get("isim") or "Ek kaynak",
                "il": kaynak.get("il") or "Türkiye",
                "ilce": kaynak.get("ilce") or "",
                "rss": rss,
                "kaynak_durumu": kaynak.get("dogrulama", "doğrulanmadı")
            })

    # Aynı RSS adresini iki kere çalıştırma.
    benzersiz = {}
    for kaynak in sonuc:
        benzersiz[str(kaynak.get("rss", "")).strip()] = kaynak

    return list(benzersiz.values())[:150]


def ana_islem():
    envanter = oku(DOSYALAR["envanter"], {})
    haberler = oku(DOSYALAR["haberler"], [])
    durum = oku(DOSYALAR["durum"], {"ilce_arama_sirasi": 0})

    if not isinstance(envanter, dict):
        raise RuntimeError("kaynaklar_ek.json biçimi hatalı.")

    if not isinstance(haberler, list):
        raise RuntimeError("haberler.json liste değil; dosya korunuyor.")

    ilceler = ilceleri_yukle()
    konular = KONULAR
    toplam = len(ilceler) * len(konular)

    baslangic = int(durum.get("ilce_arama_sirasi", 0)) % toplam
    sorgu_adedi = min(MAX_SORGU, toplam)

    kimlikler = set()

    for haber in haberler:
        if isinstance(haber, dict):
            kimlikler.add(
                haber.get("kimlik") or kimlik(
                    haber.get("link", ""),
                    haber.get("baslik", "")
                )
            )

    yeni_haberler = []

    # Mevcut RSS kaynaklarını da taramaya devam et.
    kaynaklar = kaynaklari_yukle(envanter)

    for kaynak in kaynaklar:
        url = str(kaynak.get("rss", "")).strip()

        if not url.startswith(("http://", "https://")):
            continue

        sonuc = rss_oku(
            url,
            kaynak.get("il", "Türkiye"),
            kaynak.get("ilce", ""),
            kaynak.get("ad", "Yerel RSS")
        )
        yeni_haberler.extend(sonuc)

    # İlçe ve konu taraması.
    for i in range(sorgu_adedi):
        sira = (baslangic + i) % toplam

        ilce_index = sira // len(konular)
        konu_index = sira % len(konular)

        il = ilceler[ilce_index]["il"]
        ilce = ilceler[ilce_index]["ilce"]
        konu = konular[konu_index]

        print(
            f"İlçe taranıyor: {il} / {ilce} "
            f"({i + 1}/{sorgu_adedi})"
        )

        url = google_url(il, ilce, konu)

        yeni_haberler.extend(
            rss_oku(
                url, il, ilce, "Google Haberler RSS"
            )
        )

        time.sleep(BEKLEME)

    eklenen = 0

    for haber in yeni_haberler:
        haber_id = haber.get("kimlik")

        if not haber_id or haber_id in kimlikler:
            continue

        haberler.append(haber)
        kimlikler.add(haber_id)
        eklenen += 1

    # Eski haberleri silme ve kayıt sayısını sınırlama.
    haberler.sort(
        key=lambda x: x.get("tarih", "")
        if isinstance(x, dict) else "",
        reverse=True
    )

    durum["ilce_arama_sirasi"] = (
        baslangic + sorgu_adedi
    ) % toplam

    durum["son_calisma"] = datetime.now(timezone.utc).isoformat()
    durum["son_eklenen_haber"] = eklenen
    durum["toplam_haber"] = len(haberler)
    durum["ilce_sayisi"] = len(ilceler)
    durum["toplam_sorgu"] = toplam
    durum["bu_calisma_sorgu"] = sorgu_adedi
    durum["tam_tarama_tamamlandi"] = (
        durum["ilce_arama_sirasi"] == 0
    )

    yaz(DOSYALAR["haberler"], haberler)
    yaz(DOSYALAR["durum"], durum)

    print("MİHVER taraması tamamlandı.")
    print("İlçe sayısı:", len(ilceler))
    print("Bu çalışmadaki sorgu:", sorgu_adedi)
    print("Toplam sorgu:", toplam)
    print("Yeni haber sayısı:", eklenen)
    print("Toplam haber:", len(haberler))
    print("Sonraki tarama sırası:", durum["ilce_arama_sirasi"])
    print("Tam tarama turu tamamlandı:", durum["tam_tarama_tamamlandi"])


if __name__ == "__main__":
    ana_islem()
