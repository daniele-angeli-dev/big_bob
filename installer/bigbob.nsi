; Installer di BIG-BOB (NSIS 3). Si compila con installer/build.sh.
; Installa per l'utente corrente, senza permessi di amministratore. I dati personali non vengono mai toccati.

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "TextFunc.nsh"
!include "WordFunc.nsh"
!include "nsDialogs.nsh"

!ifndef VERSION
  !define VERSION "dev"
!endif
!ifndef SRC
  !define SRC "build/app"
!endif
!ifndef OUT
  !define OUT "build/BIG-BOB-Setup.exe"
!endif
!define REGKEY "Software\BIG-BOB"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\BIG-BOB"
!define UNINSTEXE "Disinstalla BIG-BOB.exe"
!define GUIDE_URL "https://docs.claude.com/en/docs/claude-code/setup"

Name "BIG-BOB"
Caption "Installazione di BIG-BOB"
OutFile "${OUT}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\BIG-BOB"
InstallDirRegKey HKCU "${REGKEY}" "InstallDir"
SetCompressor /SOLID lzma
BrandingText "BIG-BOB ${VERSION}"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=1040 "ProductName" "BIG-BOB"
VIAddVersionKey /LANG=1040 "FileDescription" "Installazione di BIG-BOB, coach per Origins TCG"
VIAddVersionKey /LANG=1040 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1040 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1040 "CompanyName" "Daniele"
VIAddVersionKey /LANG=1040 "LegalCopyright" "Daniele"

; ---------------------------------------------------------------- aspetto
!define MUI_ICON "../ui/bigbob.ico"
!define MUI_UNICON "../ui/bigbob.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "benvenuto.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "benvenuto.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "intestazione.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "intestazione.bmp"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "Vuoi davvero interrompere l'installazione di BIG-BOB?"

!define MUI_WELCOMEPAGE_TITLE "Installa BIG-BOB"
!define MUI_WELCOMEPAGE_TEXT "BIG-BOB è il tuo coach per Origins TCG.$\r$\n$\r$\nL'installazione:$\r$\n  • controlla Python, Claude Code e Git (e installa quello che manca)$\r$\n  • copia BIG-BOB e installa le sue librerie$\r$\n  • crea l'icona sul desktop e nel menu Start$\r$\n$\r$\nI tuoi dati (carte, regole, lezioni, partite, impostazioni) non vengono mai toccati.$\r$\n$\r$\nSe BIG-BOB è aperto, chiudilo prima di continuare.$\r$\n$\r$\nVersione ${VERSION}"
!insertmacro MUI_PAGE_WELCOME
Page custom PaginaManutenzione PaginaManutenzioneLascia

!define MUI_DIRECTORYPAGE_TEXT_TOP "Cartella di BIG-BOB. Se l'avevi già installato (per esempio in C:\BIG-BOB) usa la stessa cartella: il codice viene aggiornato e i tuoi dati restano."
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
Page custom PaginaCollega PaginaCollegaLascia

!define MUI_FINISHPAGE_TITLE "BIG-BOB è pronto"
!define MUI_FINISHPAGE_TEXT "Da ora lo apri dall'icona BIG-BOB sul desktop o nel menu Start.$\r$\n$\r$\nLa prima volta apri anche «Claude Code (BIG-BOB)» dal menu Start e accetta la fiducia per la cartella e il server «origins».$\r$\n$\r$\nPer aggiornarlo: menu Start › BIG-BOB › Aggiorna BIG-BOB."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Avvia BIG-BOB"
!define MUI_FINISHPAGE_RUN_FUNCTION AvviaBigBob
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Italian"

Var PY
Var PYW
Var TESTFAIL
Var CLAUDEOK
Var CLAUDEEXE
Var Dlg
Var RbSub
Var RbApi
Var EdKey
Var DlModel
Var LbTest
Var RbDisinst

; ---------------------------------------------------------------- funzioni
!macro ChiudiBigBob
  ${Do}
    System::Call 'user32::FindWindowW(p 0, w "BIG-BOB") p .r9'
    ${If} $9 == 0
      ${Break}
    ${EndIf}
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "BIG-BOB è aperto. Chiudilo (pulsante × in alto a destra nella sua finestra) e premi Riprova." IDRETRY +2
    Abort
  ${Loop}
!macroend

Function .onInit
  ReadRegStr $0 HKCU "${REGKEY}" "InstallDir"
  ${If} $0 == ""
  ${AndIf} ${FileExists} "C:\BIG-BOB\*.*"
    StrCpy $INSTDIR "C:\BIG-BOB"
  ${EndIf}
FunctionEnd

Function ProvaPython ; $0 = comando; se va bene imposta $PY
  nsExec::ExecToStack '$0 -c "import sys;print(sys.executable) if sys.version_info>=(3,10) else sys.exit(1)"'
  Pop $1
  Pop $2
  ${If} $1 == 0
    ${TrimNewLines} "$2" $2
    ${If} ${FileExists} "$2"
      StrCpy $PY $2
    ${EndIf}
  ${EndIf}
FunctionEnd

Function TrovaPython
  StrCpy $PY ""
  StrCpy $0 "py -3"
  Call ProvaPython
  ${If} $PY == ""
    StrCpy $0 "python"
    Call ProvaPython
  ${EndIf}
  ${If} $PY == ""
    ; posti standard di un'installazione per utente
    ${If} ${FileExists} "$LOCALAPPDATA\Programs\Python\Python314\python.exe"
      StrCpy $PY "$LOCALAPPDATA\Programs\Python\Python314\python.exe"
    ${ElseIf} ${FileExists} "$LOCALAPPDATA\Programs\Python\Python313\python.exe"
      StrCpy $PY "$LOCALAPPDATA\Programs\Python\Python313\python.exe"
    ${ElseIf} ${FileExists} "$LOCALAPPDATA\Programs\Python\Python312\python.exe"
      StrCpy $PY "$LOCALAPPDATA\Programs\Python\Python312\python.exe"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function AvviaBigBob
  SetOutPath "$INSTDIR"
  Exec '"$PYW" "$INSTDIR\app.py"'
FunctionEnd

Function TrovaClaude ; percorso di claude in $CLAUDEEXE ("" se manca), anche se il PATH non è aggiornato
  StrCpy $CLAUDEEXE ""
  ${If} ${FileExists} "$PROFILE\.local\bin\claude.exe"
    StrCpy $CLAUDEEXE "$PROFILE\.local\bin\claude.exe"
    Return
  ${EndIf}
  ${If} ${FileExists} "$LOCALAPPDATA\Microsoft\WinGet\Links\claude.exe"
    StrCpy $CLAUDEEXE "$LOCALAPPDATA\Microsoft\WinGet\Links\claude.exe"
    Return
  ${EndIf}
  nsExec::ExecToStack 'cmd /c where claude'
  Pop $0
  Pop $1
  ${If} $0 == 0
    StrCpy $CLAUDEEXE "claude"
  ${EndIf}
FunctionEnd

Function Esegui ; $0 = descrizione, $1 = comando. Ritorna il codice in $2
  DetailPrint "$0..."
  nsExec::ExecToLog '$1'
  Pop $2
FunctionEnd


; ---------------------------------------------------------------- pagina: già installato
Function PaginaManutenzione
  ReadRegStr $0 HKCU "${UNINSTKEY}" "UninstallString"
  ${If} $0 == ""
    Abort ; prima installazione: pagina saltata
  ${EndIf}
  ReadRegStr $1 HKCU "${REGKEY}" "Version"
  !insertmacro MUI_HEADER_TEXT "BIG-BOB è già installato" "Versione installata: $1 · versione di questo installer: ${VERSION}"
  nsDialogs::Create 1018
  Pop $Dlg
  ${If} $Dlg == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 20u "Cosa vuoi fare?"
  Pop $0
  ${NSD_CreateRadioButton} 0 22u 100% 14u "Aggiorna o ripara BIG-BOB (i tuoi dati restano)"
  Pop $0
  ${NSD_AddStyle} $0 ${WS_GROUP}
  ${NSD_Check} $0
  ${NSD_CreateRadioButton} 0 40u 100% 14u "Disinstalla BIG-BOB"
  Pop $RbDisinst
  ${NSD_CreateLabel} 0 64u 100% 40u "Per gli aggiornamenti di tutti i giorni non serve questo installer: BIG-BOB ti avvisa da solo all'avvio quando c'è una versione nuova e si aggiorna con il pulsante AGGIORNA ORA."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function PaginaManutenzioneLascia
  ${NSD_GetState} $RbDisinst $0
  ${If} $0 == ${BST_CHECKED}
    ReadRegStr $1 HKCU "${UNINSTKEY}" "UninstallString"
    Exec '$1'
    Quit
  ${EndIf}
FunctionEnd

; ---------------------------------------------------------------- pagina: collega Claude
Function PaginaCollega
  !insertmacro MUI_HEADER_TEXT "Collega Claude" "Come BIG-BOB parla con Claude e quale modello usa"
  nsDialogs::Create 1018
  Pop $Dlg
  ${If} $Dlg == error
    Abort
  ${EndIf}
  nsExec::ExecToStack '"$PY" "$INSTDIR\configura.py" --riassunto'
  Pop $0
  Pop $1
  ${TrimNewLines} "$1" $1
  ${WordFind} "$1" "|" "+1" $R1
  ${WordFind} "$1" "|" "+2" $R2
  ${WordFind} "$1" "|" "+3" $R3

  ${If} $CLAUDEOK == "1"
    ${NSD_CreateLabel} 0 0 100% 12u "Claude Code è installato. Scegli come collegarlo:"
  ${Else}
    ${NSD_CreateLabel} 0 0 100% 12u "Claude Code non è installato: segui la guida che si è aperta, poi premi Prova collegamento."
  ${EndIf}
  Pop $0
  ${NSD_CreateRadioButton} 0 14u 100% 12u "Abbonamento Claude (consigliato): usa Claude Code con il tuo account"
  Pop $RbSub
  ${NSD_AddStyle} $RbSub ${WS_GROUP}
  ${NSD_CreateRadioButton} 0 28u 100% 12u "Chiave API Anthropic (pagamento a consumo)"
  Pop $RbApi
  ${If} $R2 == "api"
    ${NSD_Check} $RbApi
  ${Else}
    ${NSD_Check} $RbSub
  ${EndIf}
  ${If} $R3 == "si"
    ${NSD_CreateLabel} 12u 42u 30% 12u "Chiave (salvata):"
  ${Else}
    ${NSD_CreateLabel} 12u 42u 30% 12u "Chiave API:"
  ${EndIf}
  Pop $0
  ${NSD_CreatePassword} 32% 41u 66% 12u ""
  Pop $EdKey
  ${NSD_CreateLabel} 0 60u 32% 12u "Modello per le risposte:"
  Pop $0
  ${NSD_CreateDropList} 32% 58u 66% 80u ""
  Pop $DlModel
  ${NSD_CB_AddString} $DlModel "Sonnet · veloce, consigliato per il live"
  ${NSD_CB_AddString} $DlModel "Opus · più preciso, più lento"
  ${NSD_CB_AddString} $DlModel "Haiku · velocissimo, meno preciso"
  ${If} $R1 == "opus"
    ${NSD_CB_SelectString} $DlModel "Opus · più preciso, più lento"
  ${ElseIf} $R1 == "haiku"
    ${NSD_CB_SelectString} $DlModel "Haiku · velocissimo, meno preciso"
  ${Else}
    ${NSD_CB_SelectString} $DlModel "Sonnet · veloce, consigliato per il live"
  ${EndIf}
  ${NSD_CreateButton} 0 78u 48% 16u "Accedi a Claude…"
  Pop $0
  ${NSD_OnClick} $0 OnAccedi
  ${NSD_CreateButton} 52% 78u 48% 16u "Prova collegamento"
  Pop $0
  ${NSD_OnClick} $0 OnProva
  ${NSD_CreateLabel} 0 98u 100% 26u ""
  Pop $LbTest
  ${NSD_CreateLabel} 0 126u 100% 12u "Puoi cambiare tutto quando vuoi da BIG-BOB › Impostazioni (icona a ingranaggio)."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function SalvaScelte
  ${NSD_GetState} $RbApi $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $1 "api"
  ${Else}
    StrCpy $1 "abbonamento"
  ${EndIf}
  ${NSD_GetText} $DlModel $2
  StrCpy $3 $2 4
  ${If} $3 == "Opus"
    StrCpy $3 "opus"
  ${ElseIf} $3 == "Haik"
    StrCpy $3 "haiku"
  ${Else}
    StrCpy $3 "sonnet"
  ${EndIf}
  ${NSD_GetText} $EdKey $4
  ${If} $4 != ""
    nsExec::ExecToStack '"$PY" "$INSTDIR\configura.py" --modello $3 --connessione $1 --api-key "$4"'
  ${Else}
    nsExec::ExecToStack '"$PY" "$INSTDIR\configura.py" --modello $3 --connessione $1'
  ${EndIf}
  Pop $0
  Pop $0
FunctionEnd

Function OnAccedi
  Pop $0
  ${If} $CLAUDEEXE == ""
    StrCpy $CLAUDEEXE "claude"
  ${EndIf}
  Exec '"$SYSDIR\cmd.exe" /c start "Accedi a Claude" /d "$INSTDIR" cmd /k "$CLAUDEEXE"'
  ${NSD_SetText} $LbTest "Si è aperto Claude Code: segui le istruzioni per accedere (se non te lo chiede scrivi /login e scegli il tuo account). Poi torna qui e premi Prova collegamento."
FunctionEnd

Function OnProva
  Pop $0
  Call SalvaScelte
  ${NSD_SetText} $LbTest "Provo il collegamento… (fino a un minuto e mezzo)"
  nsExec::ExecToStack /TIMEOUT=100000 '"$PY" "$INSTDIR\configura.py" --prova'
  Pop $0
  Pop $1
  ${TrimNewLines} "$1" $1
  ${If} $0 == 0
    ${NSD_SetText} $LbTest "✓ $1"
  ${Else}
    ${NSD_SetText} $LbTest "✗ $1"
  ${EndIf}
FunctionEnd

Function PaginaCollegaLascia
  Call SalvaScelte
FunctionEnd

; ---------------------------------------------------------------- installazione
Section "BIG-BOB" SecMain
  SectionIn RO
  !insertmacro ChiudiBigBob

  ; --- Python
  DetailPrint "Cerco Python 3.10 o più recente..."
  Call TrovaPython
  ${If} $PY == ""
    MessageBox MB_YESNO|MB_ICONQUESTION "Python non è installato (serve la versione 3.10 o più recente).$\r$\n$\r$\nLo installo adesso con winget di Microsoft? Ci vuole circa un minuto." IDNO no_python
    StrCpy $0 "Installo Python 3.13 con winget"
    StrCpy $1 'winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements'
    Call Esegui
    Call TrovaPython
    no_python:
  ${EndIf}
  ${If} $PY == ""
    MessageBox MB_OK|MB_ICONSTOP "Non trovo Python. Installalo da python.org (spunta «Add python.exe to PATH») e poi rilancia questo installer."
    ExecShell "open" "https://www.python.org/downloads/"
    Abort
  ${EndIf}
  DetailPrint "Python: $PY"
  ${GetParent} "$PY" $0
  StrCpy $PYW "$0\pythonw.exe"
  ${IfNot} ${FileExists} "$PYW"
    StrCpy $PYW "$PY"
  ${EndIf}

  ; --- Claude Code (se manca lo installo: installer ufficiale, poi winget)
  Call TrovaClaude
  ${If} $CLAUDEEXE == ""
    StrCpy $0 "Installo Claude Code (installer ufficiale, uno o due minuti)"
    StrCpy $1 'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"'
    Call Esegui
    Call TrovaClaude
  ${EndIf}
  ${If} $CLAUDEEXE == ""
    StrCpy $0 "Installo Claude Code con winget"
    StrCpy $1 'winget install -e --id Anthropic.ClaudeCode --silent --accept-package-agreements --accept-source-agreements'
    Call Esegui
    Call TrovaClaude
  ${EndIf}
  ${If} $CLAUDEEXE == ""
    StrCpy $CLAUDEOK "0"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Non sono riuscito a installare Claude Code. BIG-BOB si installa lo stesso e riprova da solo al primo avvio.$\r$\n$\r$\nTi apro la guida ufficiale nel caso serva farlo a mano."
    ExecShell "open" "${GUIDE_URL}"
  ${Else}
    StrCpy $CLAUDEOK "1"
    DetailPrint "Claude Code: $CLAUDEEXE"
  ${EndIf}

  ; --- Git (serve per «Aggiorna BIG-BOB»)
  nsExec::ExecToStack 'cmd /c where git'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_YESNO|MB_ICONQUESTION "Git non è installato: serve solo per aggiornare BIG-BOB con un clic.$\r$\n$\r$\nLo installo adesso con winget? (Windows potrebbe chiederti il permesso)" IDNO no_git
    StrCpy $0 "Installo Git con winget"
    StrCpy $1 'winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements'
    Call Esegui
    no_git:
  ${Else}
    DetailPrint "Git: trovato"
  ${EndIf}

  ; --- File di BIG-BOB (solo codice: data, config.json, logs e captures non sono nel pacchetto)
  DetailPrint "Copio BIG-BOB in $INSTDIR..."
  SetOutPath "$INSTDIR"
  File /r "${SRC}/*.*"
  CreateDirectory "$INSTDIR\data"
  CreateDirectory "$INSTDIR\captures\scan"

  ; --- Librerie e configurazione
  StrCpy $0 "Installo le librerie Python (può richiedere qualche minuto)"
  StrCpy $1 '"$PY" -m pip install --disable-pip-version-check -r "$INSTDIR\requirements.txt"'
  Call Esegui
  ${If} $2 != 0
    MessageBox MB_OK|MB_ICONSTOP "L'installazione delle librerie non è riuscita (i dettagli sono nell'elenco). Controlla la connessione a internet e rilancia l'installer."
    Abort
  ${EndIf}
  StrCpy $0 "Aggiungo Claude Code al PATH (se serve)"
  StrCpy $1 '"$PY" "$INSTDIR\configura.py" --trova-claude'
  Call Esegui
  StrCpy $0 "Collego BIG-BOB a Claude Code"
  StrCpy $1 '"$PY" "$INSTDIR\setup_mcp.py"'
  Call Esegui

  ; --- Collaudo
  StrCpy $TESTFAIL ""
  StrCpy $0 "Collaudo: database e probabilità"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_core.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL database"
  ${EndIf}
  StrCpy $0 "Collaudo: finestra e Claude Code"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_controller.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL finestra"
  ${EndIf}
  StrCpy $0 "Collaudo: simulatore e laboratorio"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_sim.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL simulatore"
  ${EndIf}
  StrCpy $0 "Collaudo: meta da OriginsMeta"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_originsmeta.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL originsmeta"
  ${EndIf}
  StrCpy $0 "Collaudo: pagina cosa ho imparato"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_imparato.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL imparato"
  ${EndIf}
  StrCpy $0 "Collaudo: creazione mazzo"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_deckproj.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL creazione-mazzo"
  ${EndIf}
  StrCpy $0 "Collaudo: cervello comune"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_cervello.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL cervello-comune"
  ${EndIf}
  StrCpy $0 "Collaudo: mazzo avversario"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_archetype.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL mazzo-avversario"
  ${EndIf}
  StrCpy $0 "Collaudo: cronologia delle partite"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_history.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL cronologia"
  ${EndIf}
  StrCpy $0 "Collaudo: pilota automatico"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_pilot.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL pilota"
  ${EndIf}
  StrCpy $0 "Collaudo: analisi delle partite e taratura"
  StrCpy $1 '"$PY" "$INSTDIR\tests\test_tuning.py"'
  Call Esegui
  ${If} $2 != 0
    StrCpy $TESTFAIL "$TESTFAIL analisi"
  ${EndIf}
  ${If} $TESTFAIL != ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Alcuni collaudi non sono passati:$TESTFAIL.$\r$\nBIG-BOB è installato lo stesso: mandami l'elenco dei dettagli (tasto destro › Copia i dettagli negli appunti)."
  ${EndIf}

  ; --- Icone (desktop + menu Start)
  StrCpy $0 "Creo l'icona sul desktop e nel menu Start"
  StrCpy $1 '"$PY" "$INSTDIR\collegamenti.py" installa'
  Call Esegui

  ; --- Registrazione in «App installate»
  WriteRegStr HKCU "${REGKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "Python" "$PY"
  WriteRegStr HKCU "${REGKEY}" "Version" "${VERSION}"
  WriteUninstaller "$INSTDIR\${UNINSTEXE}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "BIG-BOB"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "Daniele"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\ui\bigbob.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\${UNINSTEXE}"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" "$0"
  DetailPrint "Fatto."
SectionEnd

; ---------------------------------------------------------------- disinstallazione
Section "Uninstall"
  !insertmacro ChiudiBigBob
  Delete "$DESKTOP\BIG-BOB.lnk"
  RMDir /r "$SMPROGRAMS\BIG-BOB"
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Vuoi cancellare anche i TUOI DATI?$\r$\n(carte, regole, lezioni, mazzi, partite, diari e impostazioni)$\r$\n$\r$\nScegli No per tenerli: se reinstalli BIG-BOB nella stessa cartella li ritrovi." IDYES tutto
  ; solo il codice
  RMDir /r "$INSTDIR\origins"
  RMDir /r "$INSTDIR\ui"
  RMDir /r "$INSTDIR\tests"
  RMDir /r "$INSTDIR\.claude"
  RMDir /r "$INSTDIR\.git"
  Delete "$INSTDIR\*.py"
  Delete "$INSTDIR\*.bat"
  Delete "$INSTDIR\*.md"
  Delete "$INSTDIR\requirements.txt"
  Delete "$INSTDIR\VERSION"
  Delete "$INSTDIR\.gitignore"
  Delete "$INSTDIR\.mcp.json"
  Delete "$INSTDIR\${UNINSTEXE}"
  DetailPrint "Codice rimosso. I tuoi dati restano in $INSTDIR"
  Goto registro
  tutto:
  RMDir /r "$INSTDIR"
  registro:
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "${REGKEY}"
SectionEnd
