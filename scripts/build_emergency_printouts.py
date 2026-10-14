#!/usr/bin/env python3
"""Build blank offline A4 recovery sheets; never accept secret input."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/handbook/print'
INK = colors.HexColor('#173044')
MARGIN = 48
WIDTH, HEIGHT = A4
CONTENT = WIDTH - 2 * MARGIN
STYLE = ParagraphStyle('body', fontName='Helvetica', fontSize=10, leading=14, textColor=INK)

TEXT = {
 'DE': {
  'title': 'Privates Notfallblatt', 'subtitle': 'Nur nach dem Ausdruck von Hand ergänzen',
  'intro': 'Nur notwendige Geheimnisse eintragen, die nicht aus Vaults oder Passwortmanager erreichbar sind. Bereits gesicherte Werte nur referenzieren. Nicht benötigte Felder streichen. Das ausgefüllte Blatt niemals hochladen, scannen oder fotografieren.',
  'page1': [
   ('Installation / Verantwortliche Person / Prüfdatum', 44),
   ('Notfallpaket: Aufbewahrungsort / berechtigte Person / Ersatzkopie', 55),
   ('Vault: Datei oder Vault-ID / Wiederherstellungsweg / Eintragsverweis', 62),
   ('Vault-Entschlüsselungsgeheimnis: nur falls sonst nicht erreichbar', 78),
   ('Notfallanmeldung: System / Zugang / Benutzer / Grund der Ausnahme', 65),
   ('Notfall-Passwort: nur falls nicht sicher aus anderem Speicher erreichbar', 78),
  ],
  'page2': [
   ('Backup-Entschlüsselung: Sicherung / Schlüssel-Verweis / Wiederherstellungsweg', 45),
   ('Fehlender Entschlüsselungswert: nur falls außerhalb des Vaults notwendig', 58),
   ('Passwortmanager: Notfallöffnung / benötigter Wert oder Dokumentenverweis', 58),
   ('MFA-Wiederherstellung: System / benötigte Ersatzcodes / separater Aufbewahrungsort', 72),
   ('Weitere begründete Ausnahme: System / Zweck / tatsächlich fehlender geheimer Wert', 62),
   ('Zugriff getestet durch / Datum / unabhängiger Kontakt / nächste Prüfung', 45),
  ],
  'note': 'Private Schlüssel und komplette Vault-Inhalte nicht hier abschreiben. Umfangreiche Schlüsseldateien gesondert geschützt aufbewahren und nur referenzieren. Nach Änderungen veraltete Papierkopien nach der vereinbarten Regel ersetzen.',
  'footer': 'VERTRAULICH NACH DEM AUSFÜLLEN | Leere öffentliche Vorlage | Ausgabe 1.0',
 },
 'EN': {
  'title': 'Private recovery sheet', 'subtitle': 'Complete by hand only after printing',
  'intro': 'Enter only necessary secrets unavailable from vaults or a password manager. Reference values already stored securely. Cross out unused fields. Never upload, scan or photograph the completed sheet.',
  'page1': [
   ('Installation / responsible person / verification date', 44),
   ('Recovery package: location / authorized person / protected spare copy', 55),
   ('Vault: file or vault ID / recovery route / entry reference', 62),
   ('Vault unlock secret: only if otherwise unavailable', 78),
   ('Emergency login: system / access route / username / reason for exception', 65),
   ('Emergency password: only if unavailable from another secure store', 78),
  ],
  'page2': [
   ('Backup decryption: backup / key reference / recovery route', 45),
   ('Missing decryption value: only if needed outside the vault', 58),
   ('Password manager: emergency opening / required value or document reference', 58),
   ('MFA recovery: system / required replacement codes / separate storage location', 72),
   ('Other justified exception: system / purpose / actual missing secret', 62),
   ('Access tested by / date / independent contact / next review', 45),
  ],
  'note': 'Do not copy private keys or entire vault contents here. Store large key files separately under protection and record their location. Replace obsolete paper copies after changes according to the agreed policy.',
  'footer': 'CONFIDENTIAL WHEN COMPLETED | Blank public template | Edition 1.0',
 },
}

def paragraph(c, text, y, bold=False):
    style = STYLE if not bold else ParagraphStyle('label', parent=STYLE, fontName='Helvetica-Bold', fontSize=9.5, leading=13)
    p = Paragraph(escape(text), style)
    _, h = p.wrap(CONTENT, HEIGHT)
    p.drawOn(c, MARGIN, y-h)
    return y-h

def build(language):
    OUT.mkdir(parents=True, exist_ok=True)
    t = TEXT[language]
    destination = OUT / f'Emergency-Secrets-{language}.pdf'
    c = canvas.Canvas(str(destination), pagesize=A4, invariant=1)
    c.setTitle(t['title']+' - blank / leer')
    c.setAuthor('Bergen Platform')
    for number, key in enumerate(['page1', 'page2'], 1):
        c.setFillColor(INK)
        c.setFont('Helvetica-Bold', 23)
        c.drawString(MARGIN, HEIGHT-55, t['title'])
        c.setFont('Helvetica', 11)
        c.drawString(MARGIN, HEIGHT-76, t['subtitle'])
        y = paragraph(c, t['intro'], HEIGHT-94)-15
        for label, box_height in t[key]:
            y = paragraph(c, label, y, bold=True)-5
            c.setStrokeColor(colors.HexColor('#697984'))
            c.setLineWidth(.65)
            c.rect(MARGIN, y-box_height, CONTENT, box_height, stroke=1, fill=0)
            c.setStrokeColor(colors.HexColor('#D9DFE3'))
            line = y-25
            while line > y-box_height+10:
                c.line(MARGIN+9, line, WIDTH-MARGIN-9, line)
                line -= 22
            y -= box_height+13
        y = paragraph(c, t['note'], y)-8
        if y < 43:
            raise RuntimeError(f'{language} page {number}: content overflow')
        c.setFont('Helvetica', 8)
        c.setFillColor(INK)
        c.drawString(MARGIN, 25, t['footer'])
        c.drawRightString(WIDTH-MARGIN, 25, f'{number}/2')
        c.showPage()
    c.save()
    return destination

if __name__ == '__main__':
    for language in TEXT:
        print(build(language))
