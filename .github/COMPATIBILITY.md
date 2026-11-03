# Automatische Home-Assistant-Kompatibilitätsprüfung

Der Workflow `Compatibility` prüft täglich um 05:41 UTC sowie bei relevanten
Code-, Test- und Workflow-Änderungen. Über GitHub Actions kann er zusätzlich
manuell gestartet werden. Geplante GitHub-Läufe können sich verzögern.

Neben den bisherigen Regressionstests wird bei jedem Lauf die neueste stabile
Home-Assistant-Version auf PyPI ermittelt. Verfügbare Alpha-/Dev-, Beta- und
RC-Versionen oberhalb der stabilen Version werden ebenfalls geprüft, jeweils
die neueste pro Kanal. Nicht veröffentlichte Versionen werden nicht simuliert.

Jeder Job führt die regulären Tests und Tests gegen echten Home-Assistant-Core
aus. Die DeepL-Schnittstellen werden dabei gemockt; echte Übersetzungen oder
Anmeldungen beim Anbieter sind kein Teil dieses Checks.

Die genaue Core-, Python- und Test-Plugin-Auswahl steht in der Zusammenfassung
des Erkennungsjobs. Falls eine neue Core-Version dem Test-Plugin voraus ist,
wird dessen Core-Versionsbindung gezielt überschrieben und im Log ausgewiesen.
Fehler können deshalb auch eine Anpassung des Testgerüsts erfordern.

Fehlgeschlagene Vorschautests bleiben sichtbar und werden nicht ignoriert.
Die Prüfung installiert keine Vorabversion in deiner Home-Assistant-Instanz
und veröffentlicht keine Integration. Neue Core-Versionen erfordern keine
manuelle Änderung der Versionsliste mehr.
