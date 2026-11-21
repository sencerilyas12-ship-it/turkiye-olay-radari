
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MİHVER - Türkiye Olay Radarı
Kaynak havuzu oluşturucu.

- 81 il / 922 ilçe doğrulaması
- Her çalıştırmada 60 ilçe taraması
- Google News RSS üzerinden kaynak keşfi
- Mevcut kaynakları koruma
- Tekrarlı kaynakları engelleme
- haberler.json dosyasına kesinlikle dokunmama
- Başarısız ilçeleri yeniden deneme
"""

import json
import logging
import os
import re
import time
import hashlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parent

KAYNAK_DOSYASI = BASE / "kaynaklar.json"
ILERLEME_DOSYASI = BASE / "kaynak_havuzu_ilerleme.json"
RAPOR_DOSYASI = BASE / "kaynak_havuzu_raporu.json"

BEKLENEN_IL = 81
BEKLENEN_ILCE = 922

BATCH_SIZE = 60
TIMEOUT = 25
BEKLEME = 0.5
MAX_DENEME = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("MIHVER")


# İlçe listesi kullanıcı tarafından sağlanan metinden oluşturulmuştur.
# Çok kelimeli ilçe adları tek kayıt olarak korunmuştur.

HAM_VERI = r"""
ADANA|ALADAĞ;İMAMOĞLU;POZANTI;TUFANBEYLİ;CEYHAN;KARAİSALI;SAİMBEYLİ;YUMURTALIK;ÇUKUROVA;KARATAŞ;SARIÇAM;YÜREĞİR;FEKE;KOZAN;SEYHAN
ADIYAMAN|BESNİ;KAHTA;ÇELİKHAN;SAMSAT;GERGER;SİNCİK;GÖLBAŞI;TUT
AFYONKARAHİSAR|BAŞMAKÇI;ÇOBANLAR;EVCİLER;KIZILÖREN;ŞUHUT;BAYAT;DAZKIRI;HOCALAR;SANDIKLI;BOLVADİN;DİNAR;İHSANİYE;SİNANPAŞA;ÇAY;EMİRDAĞ;İSCEHİSAR;SULTANDAĞI
AĞRI|DİYADİN;PATNOS;DOĞUBAYAZIT;TAŞLIÇAY;ELEŞKİRT;TUTAK;HAMUR
AMASYA|GÖYNÜCEK;SULUOVA;GÜMÜŞHACIKÖY;TAŞOVA;HAMAMÖZÜ;MERZİFON
ANKARA|AKYURT;BEYPAZARI;ELMADAĞ;GÜDÜL;KEÇİÖREN;POLATLI;YENİMAHALLE;ALTINDAĞ;ÇAMLIDERE;ETİMESGUT;HAYMANA;KIZILCAHAMAM;PURSAKLAR;AYAŞ;ÇANKAYA;EVREN;KAHRAMANKAZAN;MAMAK;SİNCAN;BALA;ÇUBUK;GÖLBAŞI;KALECİK;NALLIHAN;ŞEREFLİKOÇHİSAR
ANTALYA|AKSEKİ;DÖŞEMEALTI;GÜNDOĞMUŞ;KEPEZ;MANAVGAT;AKSU;ELMALI;İBRADI;KONYAALTI;MURATPAŞA;ALANYA;FİNİKE;KAŞ;KORKUTELİ;SERİK;DEMRE;GAZİPAŞA;KEMER;KUMLUCA
ARTVİN|ARDANUÇ;KEMALPAŞA;ARHAVİ;MURGUL;BORÇKA;ŞAVŞAT;HOPA;YUSUFELİ
AYDIN|BOZDOĞAN;EFELER;KARPUZLU;KUYUCAK;YENİPAZAR;BUHARKENT;GERMENCİK;KOÇARLI;NAZİLLİ;ÇİNE;İNCİRLİOVA;KÖŞK;SÖKE;DİDİM;KARACASU;KUŞADASI;SULTANHİSAR
BALIKESİR|ALTIEYLÜL;BİGADİÇ;ERDEK;İVRİNDİ;MARMARA;AYVALIK;BURHANİYE;GÖMEÇ;KARESİ;SAVAŞTEPE;BALYA;DURSUNBEY;GÖNEN;KEPSUT;SINDIRGI;BANDIRMA;EDREMİT;HAVRAN;MANYAS;SUSURLUK
BİLECİK|BOZÜYÜK;PAZARYERİ;GÖLPAZARI;SÖĞÜT;İNHİSAR;YENİPAZAR;OSMANELİ
BİNGÖL|ADAKLI;SOLHAN;GENÇ;YAYLADERE;KARLIOVA;YEDİSU;KİĞI
BİTLİS|ADİLCEVAZ;MUTKİ;AHLAT;TATVAN;GÜROYMAK;HİZAN
BOLU|DÖRTDİVAN;MENGEN;GEREDE;MUDURNU;GÖYNÜK;SEBEN;KIBRISCIK;YENİÇAĞA
BURDUR|AĞLASUN;ÇELTİKÇİ;TEFENNİ;ALTINYAYLA;GÖLHİSAR;YEŞİLOVA;BUCAK;KARAMANLI;ÇAVDIR;KEMER
BURSA|BÜYÜKORHAN;İNEGÖL;KESTEL;ORHANELİ;YILDIRIM;GEMLİK;İZNİK;MUDANYA;ORHANGAZİ;GÜRSU;KARACABEY;MUSTAFAKEMALPAŞA;OSMANGAZİ;HARMANCIK;KELES;NİLÜFER;YENİŞEHİR
ÇANAKKALE|AYVACIK;ÇAN;GÖKÇEADA;BAYRAMİÇ;ECEABAT;LAPSEKİ;BİGA;EZİNE;YENİCE;BOZCAADA;GELİBOLU
ÇANKIRI|ATKARACALAR;ILGAZ;ORTA;BAYRAMÖREN;KIZILIRMAK;ŞABANÖZÜ;ÇERKEŞ;KORGUN;YAPRAKLI;ELDİVAN;KURŞUNLU
ÇORUM|ALACA;İSKİLİP;OĞUZLAR;UĞURLUDAĞ;BAYAT;KARGI;ORTAKÖY;BOĞAZKALE;LAÇİN;OSMANCIK;DODURGA;MECİTÖZÜ;SUNGURLU
DENİZLİ|ACIPAYAM;BEYAĞAÇ;ÇAMELİ;HONAZ;SARAYKÖY;BABADAĞ;BOZKURT;ÇARDAK;KALE;SERİNHİSAR;BAKLAN;BULDAN;ÇİVRİL;MERKEZEFENDİ;TAVAS;BEKİLLİ;ÇAL;GÜNEY;PAMUKKALE
DİYARBAKIR|BAĞLAR;ÇÜNGÜŞ;HANİ;KULP;YENİŞEHİR;BİSMİL;DİCLE;HAZRO;LİCE;ÇERMİK;EĞİL;KAYAPINAR;SİLVAN;ÇINAR;ERGANİ;KOCAKÖY;SUR
EDİRNE|ENEZ;LALAPAŞA;HAVSA;MERİÇ;İPSALA;SÜLOĞLU;KEŞAN;UZUNKÖPRÜ
ELAZIĞ|AĞIN;KARAKOÇAN;PALU;ALACAKAYA;KEBAN;SİVRİCE;ARICAK;KOVANCILAR;BASKİL;MADEN
ERZİNCAN|ÇAYIRLI;OTLUKBELİ;İLİÇ;REFAHİYE;KEMAH;TERCAN;KEMALİYE;ÜZÜMLÜ
ERZURUM|AŞKALE;HORASAN;KÖPRÜKÖY;PALANDÖKEN;TEKMAN;AZİZİYE;İSPİR;NARMAN;PASİNLER;TORTUM;ÇAT;KARAÇOBAN;OLTU;PAZARYOLU;UZUNDERE;HINIS;KARAYAZI;OLUR;ŞENKAYA;YAKUTİYE
ESKİŞEHİR|ALPU;HAN;MİHALIÇÇIK;SİVRİHİSAR;BEYLİKOVA;İNÖNÜ;ODUNPAZARI;TEPEBAŞI;ÇİFTELER;MAHMUDİYE;SARICAKAYA;GÜNYÜZÜ;MİHALGAZİ;SEYİTGAZİ
GAZİANTEP|ARABAN;NURDAĞI;YAVUZELİ;İSLAHİYE;OĞUZELİ;KARKAMIŞ;ŞAHİNBEY;NİZİP;ŞEHİTKAMİL
GİRESUN|ALUCRA;DERELİ;GÖRELE;ŞEBİNKARAHİSAR;BULANCAK;DOĞANKENT;GÜCE;TİREBOLU;ÇAMOLUK;ESPİYE;KEŞAP;YAĞLIDERE;ÇANAKÇI;EYNESİL;PİRAZİZ
GÜMÜŞHANE|KELKİT;TORUL;KÖSE;KÜRTÜN;ŞİRAN
HAKKARİ|ÇUKURCA;DERECİK;ŞEMDİNLİ;YÜKSEKOVA
HATAY|ALTINÖZÜ;DEFNE;İSKENDERUN;REYHANLI;ANTAKYA;DÖRTYOL;KIRIKHAN;SAMANDAĞ;ARSUZ;ERZİN;KUMLU;YAYLADAĞI;BELEN;HASSA;PAYAS
ISPARTA|AKSU;GÖNEN;ŞARKİKARAAĞAÇ;ATABEY;KEÇİBORLU;ULUBORLU;EĞİRDİR;SENİRKENT;YALVAÇ;GELENDOST;SÜTÇÜLER;YENİŞARBADEMLİ
MERSİN|AKDENİZ;ÇAMLIYAYLA;MUT;YENİŞEHİR;ANAMUR;ERDEMLİ;SİLİFKE;AYDINCIK;GÜLNAR;TARSUS;BOZYAZI;MEZİTLİ;TOROSLAR
İSTANBUL|ADALAR;BAĞCILAR;BAYRAMPAŞA;BEYOĞLU;ESENLER;GAZİOSMANPAŞA;KARTAL;SANCAKTEPE;SULTANGAZİ;ÜMRANİYE;ARNAVUTKÖY;BAHÇELİEVLER;BEŞİKTAŞ;BÜYÜKÇEKMECE;ESENYURT;GÜNGÖREN;KÜÇÜKÇEKMECE;SARIYER;ŞİLE;ÜSKÜDAR;ATAŞEHİR;BAKIRKÖY;BEYKOZ;ÇATALCA;EYÜPSULTAN;KADIKÖY;MALTEPE;SİLİVRİ;ŞİŞLİ;ZEYTİNBURNU;AVCILAR;BAŞAKŞEHİR;BEYLİKDÜZÜ;ÇEKMEKÖY;FATİH;KAĞITHANE;PENDİK;SULTANBEYLİ;TUZLA
İZMİR|ALİAĞA;BERGAMA;ÇEŞME;GAZİEMİR;KARŞIYAKA;KONAK;ÖDEMİŞ;TORBALI;BALÇOVA;BEYDAĞ;ÇİĞLİ;GÜZELBAHÇE;KEMALPAŞA;MENDERES;SEFERİHİSAR;URLA;BAYINDIR;BORNOVA;DİKİLİ;KARABAĞLAR;KINIK;MENEMEN;SELÇUK;BAYRAKLI;BUCA;FOÇA;KARABURUN;KİRAZ;NARLIDERE;TİRE
KARS|AKYAKA;SARIKAMIŞ;ARPAÇAY;SELİM;DİGOR;SUSUZ;KAĞIZMAN
KASTAMONU|ABANA;BOZKURT;DEVREKANİ;İNEBOLU;ŞENPAZAR;AĞLI;CİDE;DOĞANYURT;KÜRE;TAŞKÖPRÜ;ARAÇ;ÇATALZEYTİN;HANÖNÜ;PINARBAŞI;TOSYA;AZDAVAY;DADAY;İHSANGAZİ;SEYDİLER
KAYSERİ|AKKIŞLA;HACILAR;ÖZVATAN;TALAS;BÜNYAN;İNCESU;PINARBAŞI;TOMARZA;DEVELİ;KOCASİNAN;SARIOĞLAN;YAHYALI;FELAHİYE;MELİKGAZİ;SARIZ;YEŞİLHİSAR
KIRKLARELİ|BABAESKİ;PEHLİVANKÖY;DEMİRKÖY;PINARHİSAR;KOFÇAZ;VİZE;LÜLEBURGAZ
KIRŞEHİR|AKÇAKENT;KAMAN;AKPINAR;MUCUR;BOZTEPE;ÇİÇEKDAĞI
KOCAELİ|BAŞİSKELE;DİLOVASI;KANDIRA;ÇAYIROVA;GEBZE;KARAMÜRSEL;DARICA;GÖLCÜK;KARTEPE;DERİNCE;İZMİT;KÖRFEZ
KONYA|AHIRLI;BEYŞEHİR;ÇUMRA;EMİRGAZİ;HALKAPINAR;KARAPINAR;SARAYÖNÜ;TUZLUKÇU;AKÖREN;BOZKIR;DERBENT;EREĞLİ;HÜYÜK;KARATAY;SELÇUKLU;YALIHÜYÜK;AKŞEHİR;CİHANBEYLİ;DEREBUCAK;GÜNEYSINIR;ILGIN;KULU;SEYDİŞEHİR;YUNAK;ALTINEKİN;ÇELTİK;DOĞANHİSAR;HADİM;KADINHANI;MERAM;TAŞKENT
KÜTAHYA|ALTINTAŞ;DUMLUPINAR;PAZARLAR;ASLANAPA;EMET;SİMAV;ÇAVDARHİSAR;GEDİZ;ŞAPHANE;DOMANİÇ;HİSARCIK;TAVŞANLI
MALATYA|AKÇADAĞ;DARENDE;KALE;YEŞİLYURT;ARAPGİR;DOĞANŞEHİR;KULUNCAK;ARGUVAN;DOĞANYOL;PÜTÜRGE;BATTALGAZİ;HEKİMHAN;YAZIHAN
MANİSA|AHMETLİ;GÖLMARMARA;KULA;SELENDİ;YUNUSEMRE;AKHİSAR;GÖRDES;SALİHLİ;SOMA;ALAŞEHİR;KIRKAĞAÇ;SARIGÖL;ŞEHZADELER;DEMİRCİ;KÖPRÜBAŞI;SARUHANLI;TURGUTLU
KAHRAMANMARAŞ|AFŞİN;EKİNÖZÜ;ONİKİŞUBAT;ANDIRIN;ELBİSTAN;PAZARCIK;ÇAĞLAYANCERİT;GÖKSUN;TÜRKOĞLU;DULKADİROĞLU;NURHAK
MARDİN|ARTUKLU;MAZIDAĞI;SAVUR;DARGEÇİT;MİDYAT;YEŞİLLİ;DERİK;NUSAYBİN;KIZILTEPE;ÖMERLİ
MUĞLA|BODRUM;KAVAKLIDERE;MİLAS;YATAĞAN;DALAMAN;KÖYCEĞİZ;ORTACA;DATÇA;MARMARİS;SEYDİKEMER;FETHİYE;MENTEŞE;ULA
MUŞ|BULANIK;VARTO;HASKÖY;KORKUT;MALAZGİRT
NEVŞEHİR|ACIGÖL;HACIBEKTAŞ;AVANOS;KOZAKLI;DERİNKUYU;ÜRGÜP;GÜLŞEHİR
NİĞDE|ALTUNHİSAR;ULUKIŞLA;BOR;ÇAMARDI;ÇİFTLİK
ORDU|AKKUŞ;ÇATALPINAR;GÜLYALI;KABATAŞ;PERŞEMBE;ALTINORDU;ÇAYBAŞI;GÜRGENTEPE;KORGAN;ULUBEY;AYBASTI;FATSA;İKİZCE;KUMRU;ÜNYE;ÇAMAŞ;GÖLKÖY;KABADÜZ;MESUDİYE
RİZE|ARDEŞEN;FINDIKLI;İYİDERE;ÇAMLIHEMŞİN;GÜNEYSU;KALKANDERE;ÇAYELİ;HEMŞİN;PAZAR;DEREPAZARI;İKİZDERE
SAKARYA|ADAPAZARI;FERİZLİ;KARASU;SAPANCA;AKYAZI;GEYVE;KAYNARCA;SERDİVAN;ARİFİYE;HENDEK;KOCAALİ;SÖĞÜTLÜ;ERENLER;KARAPÜRÇEK;PAMUKOVA;TARAKLI
SAMSUN|19 MAYIS;AYVACIK;HAVZA;SALIPAZARI;YAKAKENT;ALAÇAM;BAFRA;İLKADIM;TEKKEKÖY;ASARCIK;CANİK;KAVAK;TERME;ATAKUM;ÇARŞAMBA;LADİK;VEZİRKÖPRÜ
SİİRT|BAYKAN;ŞİRVAN;ERUH;TİLLO;KURTALAN;PERVARİ
SİNOP|AYANCIK;ERFELEK;BOYABAT;GERZE;DİKMEN;SARAYDÜZÜ;DURAĞAN;TÜRKELİ
SİVAS|AKINCILAR;GEMEREK;İMRANLI;ŞARKIŞLA;ALTINYAYLA;GÖLOVA;KANGAL;ULAŞ;DİVRİĞİ;GÜRÜN;KOYULHİSAR;YILDIZELİ;DOĞANŞAR;HAFİK;SUŞEHRİ;ZARA
TEKİRDAĞ|ÇERKEZKÖY;KAPAKLI;SARAY;ÇORLU;MALKARA;SÜLEYMANPAŞA;ERGENE;MARMARAEREĞLİSİ;ŞARKÖY;HAYRABOLU;MURATLI
TOKAT|ALMUS;NİKSAR;TURHAL;ARTOVA;PAZAR;YEŞİLYURT;BAŞÇİFTLİK;REŞADİYE;ZİLE;ERBAA;SULUSARAY
TRABZON|AKÇAABAT;ÇARŞIBAŞI;HAYRAT;ORTAHİSAR;VAKFIKEBİR;ARAKLI;ÇAYKARA;KÖPRÜBAŞI;SÜRMENE;YOMRA;ARSİN;DERNEKPAZARI;MAÇKA;ŞALPAZARI;BEŞİKDÜZÜ;DÜZKÖY;OF;TONYA
TUNCELİ|ÇEMİŞGEZEK;OVACIK;HOZAT;PERTEK;MAZGİRT;PÜLÜMÜR;NAZIMİYE
ŞANLIURFA|AKÇAKALE;EYYÜBİYE;HİLVAN;VİRANŞEHİR;BİRECİK;HALFETİ;KARAKÖPRÜ;BOZOVA;HALİLİYE;SİVEREK;CEYLANPINAR;HARRAN;SURUÇ
UŞAK|BANAZ;ULUBEY;EŞME;KARAHALLI;SİVASLI
VAN|BAHÇESARAY;EDREMİT;İPEKYOLU;TUŞBA;BAŞKALE;ERCİŞ;MURADİYE;ÇALDIRAN;GEVAŞ;ÖZALP;ÇATAK;GÜRPINAR;SARAY
YOZGAT|AKDAĞMADENİ;ÇAYIRALAN;SARIKAYA;YERKÖY;AYDINCIK;ÇEKEREK;SORGUN;BOĞAZLIYAN;KADIŞEHRİ;ŞEFAATLİ;ÇANDIR;SARAYKENT;YENİFAKILI
ZONGULDAK|ALAPLI;GÖKÇEBEY;ÇAYCUMA;KİLİMLİ;DEVREK;KOZLU;EREĞLİ
AKSARAY|AĞAÇÖREN;ORTAKÖY;ESKİL;SARIYAHŞİ;GÜLAĞAÇ;SULTANHANI;GÜZELYURT
BAYBURT|AYDINTEPE;DEMİRÖZÜ
KARAMAN|AYRANCI;SARIVELİLER;BAŞYAYLA;ERMENEK;KAZIMKARABEKİR
KIRIKKALE|BAHŞILI;KARAKEÇİLİ;BALIŞEYH;KESKİN;ÇELEBİ;SULAKYURT;DELİCE;YAHŞİHAN
BATMAN|BEŞİRİ;SASON;GERCÜŞ;HASANKEYF;KOZLUK
ŞIRNAK|BEYTÜŞŞEBAP;SİLOPİ;CİZRE;ULUDERE;GÜÇLÜKONAK;İDİL
BARTIN|AMASRA;KURUCAŞİLE;ULUS
ARDAHAN|ÇILDIR;POSOF;DAMAL;GÖLE;HANAK
IĞDIR|ARALIK;KARAKOYUNLU;TUZLUCA
YALOVA|ALTINOVA;TERMAL;ARMUTLU;ÇINARCIK;ÇİFTLİKKÖY
KARABÜK|EFLANİ;YENİCE;ESKİPAZAR;OVACIK;SAFRANBOLU
KİLİS|ELBEYLİ;MUSABEYLİ;POLATELİ
OSMANİYE|BAHÇE;SUMBAS;DÜZİÇİ;TOPRAKKALE;HASANBEYLİ;KADİRLİ
DÜZCE|AKÇAKOCA;GÜMÜŞOVA;CUMAYERİ;KAYNAŞLI;ÇİLİMLİ;YIĞILCA;GÖLYAKA
"""


def simdi():
    return datetime.now(timezone.utc).isoformat()


def normalize(text):
    text = str(text or "").strip().upper()
    text = text.replace("İ", "İ")
    return re.sub(r"\s+", " ", text)


def ilce_listesini_olustur():
    sonuc = {}

    for satir in HAM_VERI.strip().splitlines():
        if "|" not in satir:
            continue

        il, liste = satir.split("|", 1)
        il = normalize(il)

        ilceler = [
            normalize(x)
            for x in liste.split(";")
            if normalize(x)
        ]

        if il in sonuc:
            raise RuntimeError(f"Tekrarlanan il: {il}")

        if len(ilceler) != len(set(ilceler)):
            raise RuntimeError(f"{il} içinde tekrarlanan ilçe var.")

        sonuc[il] = ilceler

    if len(sonuc) != BEKLENEN_IL:
        raise RuntimeError(
            f"İl listesi hatalı: {len(sonuc)} / {BEKLENEN_IL}"
        )

    toplam = sum(len(x) for x in sonuc.values())

    if toplam != BEKLENEN_ILCE:
        raise RuntimeError(
            f"İlçe sayısı hatalı: {toplam} / {BEKLENEN_ILCE}. "
            "Kaynak dosyalarına hiçbir kayıt yazılmadı."
        )

    return sonuc


def json_oku(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def json_yaz(path, data):
    temp = path.with_name(path.name + ".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, path)


def kaynaklari_al(data):
    if isinstance(data, list):
        return data, None

    if isinstance(data, dict):
        for key in ("kaynaklar", "sources", "items"):
            if isinstance(data.get(key), list):
                return data[key], key

    raise RuntimeError("kaynaklar.json yapısı tanınamadı.")


def url_kimligi(url):
    try:
        p = urllib.parse.urlsplit(str(url).strip())

        host = (p.hostname or "").lower()

        if host.startswith("www."):
            host = host[4:]

        path = p.path.rstrip("/")

        return host + path.lower()

    except Exception:
        return ""


def kaynak_kimligi(kaynak):
    if not isinstance(kaynak, dict):
        return ""

    url = (
        kaynak.get("url")
        or kaynak.get("link")
        or kaynak.get("adres")
        or ""
    )

    return url_kimligi(url)


def rss_sorgusu(il, ilce):
    return f'"{ilce}" "{il}" haber OR gazete OR belediye OR adliye'


def rss_oku(sorgu):
    params = urllib.parse.urlencode({
        "q": sorgu,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr"
    })

    url = "https://news.google.com/rss/search?" + params

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 MIHVER/1.0"}
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read()

    root = ET.fromstring(raw)

    results = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        article_url = (item.findtext("link") or "").strip()
        source = item.find("source")

        if source is None:
            continue

        name = (source.text or "").strip()
        source_url = (source.attrib.get("url") or "").strip()

        parsed = urllib.parse.urlsplit(source_url)

        if (
            not name
            or parsed.scheme not in ("http", "https")
            or not parsed.hostname
        ):
            continue

        host = parsed.hostname.lower()

        if host.endswith("google.com"):
            continue

        results.append({
            "ad": name,
            "url": source_url,
            "alan_adi": host.removeprefix("www."),
            "durum": "aday",
            "tur": "yerel_haber",
            "kesif_yontemi": "Google News RSS",
            "arama_sorgusu": sorgu,
            "ornek_haber_basligi": title,
            "ornek_haber_url": article_url,
            "kesif_tarihi": simdi()
        })

    return results


def ilceyi_tara(il, ilce):
    sorgu = rss_sorgusu(il, ilce)
    son_hata = None

    for deneme in range(1, MAX_DENEME + 1):
        try:
            return rss_oku(sorgu), None

        except Exception as exc:
            son_hata = str(exc)

            log.warning(
                "%s / %s sorgusu başarısız (%s/%s): %s",
                il,
                ilce,
                deneme,
                MAX_DENEME,
                exc
            )

            time.sleep(2 * deneme)

    return [], son_hata


def main():
    log.info("MİHVER kaynak havuzu başlıyor.")

    # Liste doğrulanmadan kaynak dosyası açılmaz.
    ilceler = ilce_listesini_olustur()

    tum_ilceler = [
        (il, ilce)
        for il, liste in ilceler.items()
        for ilce in liste
    ]

    if len(tum_ilceler) != BEKLENEN_ILCE:
        raise RuntimeError("Son ilçe sayısı kontrolü başarısız.")

    kaynak_verisi = json_oku(KAYNAK_DOSYASI, [])

    mevcut, kaynak_anahtari = kaynaklari_al(kaynak_verisi)

    bilinen = {
        kaynak_kimligi(k)
        for k in mevcut
        if kaynak_kimligi(k)
    }

    ilerleme = json_oku(ILERLEME_DOSYASI, {})

    baslangic = int(ilerleme.get("next_index", 0))

    if not 0 <= baslangic < len(tum_ilceler):
        baslangic = 0

    parti = tum_ilceler[baslangic:baslangic + BATCH_SIZE]

    yeni_kaynaklar = []
    hatalar = []
    basarili_ilceler = []

    for il, ilce in parti:
        log.info("Taranıyor: %s / %s", il, ilce)

        adaylar, hata = ilceyi_tara(il, ilce)

        if hata:
            hatalar.append({
                "il": il,
                "ilce": ilce,
                "hata": hata
            })
            continue

        basarili_ilceler.append((il, ilce))

        for aday in adaylar:
            aday["il"] = il
            aday["ilce"] = ilce

            kimlik = kaynak_kimligi(aday)

            if not kimlik or kimlik in bilinen:
                continue

            bilinen.add(kimlik)
            yeni_kaynaklar.append(aday)

        time.sleep(BEKLEME)

    # Hatalı ilçeleri atlamamak için tamamlanmış indeks yalnızca
    # ardışık başarılı ilçelere göre ilerletilir.
    basarili_set = set(basarili_ilceler)

    yeni_index = baslangic

    for il, ilce in parti:
        if (il, ilce) not in basarili_set:
            break
        yeni_index += 1

    tur_tamamlandi = (
        yeni_index >= len(tum_ilceler)
        and not hatalar
    )

    if tur_tamamlandi:
        yeni_index = 0

    birlesik = mevcut + yeni_kaynaklar

    # Kaynak verisi atomik olarak kaydedilir.
    if kaynak_anahtari is None:
        yeni_veri = birlesik
    else:
        yeni_veri = dict(kaynak_verisi)
        yeni_veri[kaynak_anahtari] = birlesik

    json_yaz(KAYNAK_DOSYASI, yeni_veri)

    # İlerleme kaydı kaynak kaydından sonra yazılır.
    json_yaz(
        ILERLEME_DOSYASI,
        {
            "surum": "5.0.0",
            "son_calistirma": simdi(),
            "next_index": yeni_index,
            "toplam_il": BEKLENEN_IL,
            "toplam_ilce": BEKLENEN_ILCE,
            "basarili_ilce": len(basarili_ilceler),
            "basarisiz_ilce": len(hatalar),
            "tam_tur_tamamlandi": tur_tamamlandi
        }
    )

    json_yaz(
        RAPOR_DOSYASI,
        {
            "surum": "5.0.0",
            "rapor_tarihi": simdi(),
            "toplam_il": BEKLENEN_IL,
            "toplam_ilce": BEKLENEN_ILCE,
            "bu_calistirmada_taranan_ilce": len(parti),
            "basarili_ilce": len(basarili_ilceler),
            "basarisiz_ilce": len(hatalar),
            "yeni_aday_kaynak": len(yeni_kaynaklar),
            "toplam_kaynak": len(birlesik),
            "tam_tur_tamamlandi": tur_tamamlandi,
            "hatalar": hatalar,
            "haberler_json_degistirildi": False
        }
    )

    log.info("İşlem tamamlandı.")
    log.info("Yeni kaynak: %s", len(yeni_kaynaklar))
    log.info("Başarısız ilçe: %s", len(hatalar))
    log.info("Toplam kaynak: %s", len(birlesik))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Kaynak havuzu işlemi durduruldu.")
        raise SystemExit(1)
