"""
BlueAway -- deep Bluetooth device trace remover for Windows.

Usage
-----
    python blueaway.py                     GUI
    python blueaway.py --list              list devices, exit
    python blueaway.py --plan <MAC>        show what would be removed
    python blueaway.py --remove <MAC>      dry run removal
    python blueaway.py --remove <MAC> --yes    actually remove
    python blueaway.py --json report.json --plan <MAC>

Embedding in DMod
-----------------
    from blueaway import BlueAwayWindow
    win = BlueAwayWindow(parent=self)      # any QWidget parent
    win.show()

Requires: PyQt5, and pywin32 for registry ownership escalation
(``pip install PyQt5 pywin32``). Without pywin32 everything still works
except taking ownership of protected keys.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import Dict, List, Optional

import blueaway_core as core

APP_NAME = "BlueAway"
APP_VERSION = "2.0"


def default_backup_dir() -> str:
    base = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    return os.path.join(base, "BlueAway_Backups")


# ==========================================================================
# CLI
# ==========================================================================

def run_cli(args) -> int:
    if not core.is_admin():
        print("! Not elevated. Registry writes will fail.", file=sys.stderr)

    print("Indexing registry (one pass)...")
    index = core.RegistryIndex()
    index.build(progress=lambda path, n: None)
    print(f"  {len(index.records)} keys indexed in {index.elapsed:.1f}s"
          + ("  [TRUNCATED]" if index.truncated else ""))

    adapters = core.get_adapter_macs()
    devices = core.discover_devices(index)

    if args.list or not (args.plan or args.remove):
        print(f"\nLocal radios: {', '.join(core.pretty_mac(a) for a in sorted(adapters)) or 'none'}")
        print(f"\n{len(devices)} Bluetooth device(s):\n")
        for d in devices:
            print(f"  {core.pretty_mac(d.mac)}  [{d.kind_label:<14}]  {d.display}")
        return 0

    target_mac = core.norm_mac(args.plan or args.remove)
    if not target_mac:
        print("Invalid MAC address.", file=sys.stderr)
        return 2
    match = next((d for d in devices if d.mac == target_mac), None)
    if not match:
        print(f"No device with MAC {core.pretty_mac(target_mac)}", file=sys.stderr)
        return 2

    print(f"\nAnalysing {match.display} ({core.pretty_mac(match.mac)})...")
    plan = core.build_plan(match, index, adapters, log=print)

    print(f"\n{len(plan.identity)} identifiers, {len(plan.references)} references:\n")
    for r in plan.references:
        extra = (" :: " + ", ".join(r.value_names)) if r.value_names else ""
        print(f"  [{r.confidence:<6}][{r.action:<13}] {r.record.full}{extra}")
    for n in plan.notes:
        print(f"  note: {n}")

    if args.json:
        core.save_report(plan, args.json)
        print(f"\nReport written to {args.json}")

    if not args.remove:
        return 0

    selected = [r for r in plan.references
                if r.confidence in ("HIGH", "MEDIUM")
                and not r.reason.startswith("protected")]
    dry = not args.yes
    print(f"\n{'DRY RUN' if dry else 'REMOVING'} -- {len(selected)} action(s)\n")
    core.execute_plan(plan, selected, args.backup_dir or default_backup_dir(),
                      dry_run=dry, log=print)
    if dry:
        print("\nNothing was changed. Re-run with --yes to apply.")
    return 0


# ==========================================================================
# GUI
# ==========================================================================

try:
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (
        QAbstractItemView, QApplication, QCheckBox, QDialog, QFileDialog,
        QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox,
        QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTreeWidget,
        QTreeWidgetItem, QVBoxLayout, QWidget)
    HAVE_QT = True
except Exception:                                       # pragma: no cover
    HAVE_QT = False


DARK_QSS = """
QWidget          { background:#1e1e1e; color:#e6e6e6;
                   font-family:'Segoe UI'; font-size:9pt; }
QTreeWidget      { background:#252526; alternate-background-color:#2a2a2b;
                   border:1px solid #3a3a3c; }
QTreeWidget::item:selected { background:#0a5f9e; }
QHeaderView::section { background:#333336; color:#dcdcdc; padding:4px;
                   border:0; border-right:1px solid #1e1e1e; }
QPlainTextEdit   { background:#141414; color:#9fe39f;
                   font-family:'Consolas'; font-size:8.5pt;
                   border:1px solid #3a3a3c; }
QPushButton      { background:#3a3a3d; border:1px solid #4a4a4d;
                   padding:6px 12px; border-radius:2px; }
QPushButton:hover  { background:#48484c; }
QPushButton:disabled { background:#2a2a2b; color:#666; }
QPushButton#danger { background:#a02b2b; border-color:#c04040; font-weight:bold; }
QPushButton#danger:hover   { background:#c03434; }
QPushButton#danger:disabled{ background:#4a2323; color:#8a6a6a; }
QPushButton#primary { background:#1d6fa5; border-color:#2a8bc9; }
QPushButton#primary:hover { background:#2481bd; }
QProgressBar     { background:#252526; border:1px solid #3a3a3c;
                   text-align:center; height:16px; }
QProgressBar::chunk { background:#1d6fa5; }
QLabel#title     { font-size:13pt; font-weight:bold; color:#6cb6ff; }
QCheckBox        { padding:2px; }
"""

CONF_COLOR = {
    "HIGH":   QColor("#ff8080") if HAVE_QT else None,
    "MEDIUM": QColor("#ffcc66") if HAVE_QT else None,
    "LOW":    QColor("#9a9a9a") if HAVE_QT else None,
}

CONF_BLURB = {
    "HIGH": "Certain -- the key is named after this device",
    "MEDIUM": "Derived -- reached by following this device's container/endpoint",
    "LOW": "Mentions only -- shared key that merely references the device",
}


if HAVE_QT:

    class ScanThread(QThread):
        progress = pyqtSignal(str, int)
        finished_ok = pyqtSignal(object, object, object)
        failed = pyqtSignal(str)

        def run(self):
            try:
                index = core.RegistryIndex()
                index.build(progress=lambda p, n: self.progress.emit(p, n))
                adapters = core.get_adapter_macs()
                devices = core.discover_devices(index)
                self.finished_ok.emit(index, devices, adapters)
            except Exception:
                self.failed.emit(traceback.format_exc())

    class PlanThread(QThread):
        log = pyqtSignal(str)
        finished_ok = pyqtSignal(object)
        failed = pyqtSignal(str)

        def __init__(self, device, index, adapters):
            super().__init__()
            self.device, self.index, self.adapters = device, index, adapters

        def run(self):
            try:
                plan = core.build_plan(self.device, self.index, self.adapters,
                                       log=lambda m: self.log.emit(m))
                self.finished_ok.emit(plan)
            except Exception:
                self.failed.emit(traceback.format_exc())

    class ExecThread(QThread):
        log = pyqtSignal(str)
        finished_ok = pyqtSignal(object)
        failed = pyqtSignal(str)

        def __init__(self, plan, selected, backup_dir, dry, unpair, pnp, restart):
            super().__init__()
            self.plan, self.selected = plan, selected
            self.backup_dir, self.dry = backup_dir, dry
            self.unpair, self.pnp, self.restart = unpair, pnp, restart

        def run(self):
            try:
                res = core.execute_plan(
                    self.plan, self.selected, self.backup_dir,
                    dry_run=self.dry, do_unpair=self.unpair,
                    do_pnp=self.pnp, do_restart=self.restart,
                    log=lambda m: self.log.emit(m))
                self.finished_ok.emit(res)
            except Exception:
                self.failed.emit(traceback.format_exc())

    class AudioGatewayThread(QThread):
        log = pyqtSignal(str)
        finished_ok = pyqtSignal(bool)
        failed = pyqtSignal(str)

        def run(self):
            try:
                ok = core.restart_audio_gateway(log=lambda m: self.log.emit(m))
                self.finished_ok.emit(ok)
            except Exception:
                self.failed.emit(traceback.format_exc())

    # ------------------------------------------------------------------

    class BackupDialog(QDialog):
        def __init__(self, backup_dir: str, parent=None):
            super().__init__(parent)
            self.backup_dir = backup_dir
            self.setWindowTitle("BlueAway - Backups")
            self.resize(760, 420)
            self.setStyleSheet(DARK_QSS)

            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(f"Registry backups in {backup_dir}"))

            self.tree = QTreeWidget()
            self.tree.setHeaderLabels(["File", "Size", "Created"])
            self.tree.setRootIsDecorated(False)
            self.tree.setAlternatingRowColors(True)
            self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
            lay.addWidget(self.tree)

            row = QHBoxLayout()
            for text, slot, oid in (
                    ("Open folder", self.open_folder, ""),
                    ("Restore selected", self.restore, "primary"),
                    ("Delete selected", self.delete, "danger")):
                b = QPushButton(text)
                if oid:
                    b.setObjectName(oid)
                b.clicked.connect(slot)
                row.addWidget(b)
            row.addStretch(1)
            close = QPushButton("Close")
            close.clicked.connect(self.accept)
            row.addWidget(close)
            lay.addLayout(row)

            self.reload()

        def reload(self):
            self.tree.clear()
            if not os.path.isdir(self.backup_dir):
                return
            import datetime
            for name in sorted(os.listdir(self.backup_dir), reverse=True):
                if not name.lower().endswith(".reg"):
                    continue
                p = os.path.join(self.backup_dir, name)
                st = os.stat(p)
                ts = datetime.datetime.fromtimestamp(st.st_mtime)
                QTreeWidgetItem(self.tree, [
                    name, f"{st.st_size:,} B",
                    ts.strftime("%Y-%m-%d %H:%M:%S")])

        def _selected_path(self) -> Optional[str]:
            it = self.tree.currentItem()
            return os.path.join(self.backup_dir, it.text(0)) if it else None

        def open_folder(self):
            os.makedirs(self.backup_dir, exist_ok=True)
            os.startfile(self.backup_dir)

        def restore(self):
            p = self._selected_path()
            if not p:
                return
            if QMessageBox.question(
                    self, "Restore",
                    f"Merge {os.path.basename(p)} back into the registry?\n\n"
                    "This re-adds the keys but will not re-pair the device.",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            rc, out = core._run(["reg.exe", "import", p])
            QMessageBox.information(
                self, "Restore",
                "Restored." if rc == 0 else f"reg import failed:\n{out}")

        def delete(self):
            p = self._selected_path()
            if not p:
                return
            if QMessageBox.question(self, "Delete",
                                    f"Delete {os.path.basename(p)}?",
                                    QMessageBox.Yes | QMessageBox.No) \
                    == QMessageBox.Yes:
                try:
                    os.remove(p)
                except OSError as exc:
                    QMessageBox.warning(self, "Delete", str(exc))
                self.reload()

    # ------------------------------------------------------------------

    class BlueAwayWindow(QMainWindow):
        """Main window. Safe to construct with a parent and embed in DMod."""

        def __init__(self, parent=None, backup_dir: Optional[str] = None):
            super().__init__(parent)
            self.setWindowTitle(f"{APP_NAME} {APP_VERSION} - "
                                f"Deep Bluetooth Trace Remover")
            self.resize(1180, 760)
            self.setStyleSheet(DARK_QSS)

            self.backup_dir = backup_dir or default_backup_dir()
            self.index: Optional[core.RegistryIndex] = None
            self.devices: List[core.BtDevice] = []
            self.adapters = set()
            self.plan: Optional[core.Plan] = None
            self._threads = []

            self._build_ui()
            self.start_scan()

        # -- UI ---------------------------------------------------------

        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            root = QVBoxLayout(central)
            root.setContentsMargins(10, 8, 10, 8)

            title = QLabel(f"{APP_NAME} - Deep Bluetooth Trace Remover")
            title.setObjectName("title")
            root.addWidget(title)

            sub = QLabel(
                "Select a device, analyse it, review every reference found, "
                "then remove. Nothing is touched until you press Remove with "
                "dry run unchecked.")
            sub.setStyleSheet("color:#9a9a9a;")
            sub.setWordWrap(True)
            root.addWidget(sub)

            split = QSplitter(Qt.Horizontal)
            root.addWidget(split, 1)

            # left: devices
            left = QWidget()
            lv = QVBoxLayout(left)
            lv.setContentsMargins(0, 0, 0, 0)
            lv.addWidget(QLabel("Bluetooth devices"))
            self.devTree = QTreeWidget()
            self.devTree.setHeaderLabels(["Device", "MAC", "Type"])
            self.devTree.setRootIsDecorated(False)
            self.devTree.setAlternatingRowColors(True)
            self.devTree.setSelectionMode(QAbstractItemView.SingleSelection)
            self.devTree.header().setSectionResizeMode(0, QHeaderView.Stretch)
            self.devTree.setColumnWidth(1, 140)
            self.devTree.setColumnWidth(2, 90)
            self.devTree.itemSelectionChanged.connect(self._device_changed)
            self.devTree.itemDoubleClicked.connect(lambda *_: self.analyse())
            lv.addWidget(self.devTree, 1)

            drow = QHBoxLayout()
            self.btnRescan = QPushButton("Rescan registry")
            self.btnRescan.clicked.connect(self.start_scan)
            drow.addWidget(self.btnRescan)
            self.btnAnalyse = QPushButton("Analyse ->")
            self.btnAnalyse.setObjectName("primary")
            self.btnAnalyse.setEnabled(False)
            self.btnAnalyse.clicked.connect(self.analyse)
            drow.addWidget(self.btnAnalyse)
            lv.addLayout(drow)
            split.addWidget(left)

            # right: plan
            right = QWidget()
            rv = QVBoxLayout(right)
            rv.setContentsMargins(0, 0, 0, 0)
            self.planLabel = QLabel("References found")
            rv.addWidget(self.planLabel)
            self.planTree = QTreeWidget()
            self.planTree.setHeaderLabels(
                ["Registry key", "Action", "Why it was matched"])
            self.planTree.setAlternatingRowColors(True)
            self.planTree.header().setSectionResizeMode(0, QHeaderView.Stretch)
            self.planTree.setColumnWidth(1, 120)
            self.planTree.setColumnWidth(2, 300)
            self.planTree.itemChanged.connect(self._item_checked)
            rv.addWidget(self.planTree, 1)

            opts = QHBoxLayout()
            self.chkDry = QCheckBox("Dry run (change nothing)")
            self.chkDry.setChecked(True)
            self.chkUnpair = QCheckBox("Unpair via Windows API first")
            self.chkUnpair.setChecked(True)
            self.chkPnp = QCheckBox("Remove PnP nodes")
            self.chkPnp.setChecked(True)
            self.chkRestart = QCheckBox("Restart BT services")
            self.chkRestart.setChecked(True)
            for c in (self.chkDry, self.chkUnpair, self.chkPnp, self.chkRestart):
                opts.addWidget(c)
            opts.addStretch(1)
            rv.addLayout(opts)

            arow = QHBoxLayout()
            self.btnBackups = QPushButton("Backups...")
            self.btnBackups.clicked.connect(self.show_backups)
            arow.addWidget(self.btnBackups)
            self.btnFixHfp = QPushButton("Fix Hands-Free Audio")
            self.btnFixHfp.setToolTip(
                "Restarts the Bluetooth Audio Gateway Service to force "
                "Windows to rebuild the Hands-Free audio device after a "
                "headset reconnects. No pairing/registry changes.")
            self.btnFixHfp.clicked.connect(self.fix_handsfree_audio)
            arow.addWidget(self.btnFixHfp)
            self.btnReport = QPushButton("Export report")
            self.btnReport.setEnabled(False)
            self.btnReport.clicked.connect(self.export_report)
            arow.addWidget(self.btnReport)
            arow.addStretch(1)
            self.btnRemove = QPushButton("REMOVE CHECKED")
            self.btnRemove.setObjectName("danger")
            self.btnRemove.setEnabled(False)
            self.btnRemove.clicked.connect(self.remove)
            arow.addWidget(self.btnRemove)
            rv.addLayout(arow)
            split.addWidget(right)
            split.setSizes([400, 780])

            self.progress = QProgressBar()
            self.progress.setRange(0, 0)
            self.progress.hide()
            root.addWidget(self.progress)

            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumHeight(190)
            root.addWidget(self.log)

            if not core.is_admin():
                self._log("[!] Not running elevated -- removal will fail. "
                          "Restart as Administrator.")
            if not core._PYWIN32:
                self._log("[!] pywin32 not installed -- cannot take ownership "
                          "of protected keys. pip install pywin32")

        def _log(self, msg: str):
            self.log.appendPlainText(msg)
            self.log.verticalScrollBar().setValue(
                self.log.verticalScrollBar().maximum())

        def _busy(self, on: bool, msg: str = ""):
            self.progress.setVisible(on)
            for w in (self.btnRescan, self.btnAnalyse, self.btnRemove,
                      self.devTree):
                w.setEnabled(not on)
            if not on:
                self._device_changed()
                self.btnRemove.setEnabled(self.plan is not None)
            if msg:
                self._log(msg)

        # -- scan -------------------------------------------------------

        def start_scan(self):
            self._busy(True, "[~] Indexing registry (single pass)...")
            self.devTree.clear()
            self.planTree.clear()
            self.plan = None
            t = ScanThread()
            t.progress.connect(
                lambda p, n: self.progress.setFormat(f"{n:,} keys - {p[:70]}"))
            t.finished_ok.connect(self._scan_done)
            t.failed.connect(self._thread_failed)
            self._threads.append(t)
            self.progress.setFormat("%p%")
            t.start()

        def _scan_done(self, index, devices, adapters):
            self.index, self.devices, self.adapters = index, devices, adapters
            self._log(f"[+] Indexed {len(index.records):,} keys in "
                      f"{index.elapsed:.1f}s"
                      + ("  (LIMIT HIT)" if index.truncated else ""))
            self._log(f"[+] Local radios: "
                      + (", ".join(core.pretty_mac(a) for a in sorted(adapters))
                         or "none detected"))
            for d in devices:
                it = QTreeWidgetItem(self.devTree,
                                     [d.display, core.pretty_mac(d.mac),
                                      d.kind_label])
                it.setData(0, Qt.UserRole, d)
                if not d.paired:
                    it.setForeground(0, QColor("#c9a227"))
                    it.setToolTip(0, "Leftover / unpaired -- safe to remove")
            self._log(f"[+] {len(devices)} device(s) found.")
            self._busy(False)

        def _thread_failed(self, tb: str):
            self._busy(False)
            self._log("[-] " + tb.strip().splitlines()[-1])
            QMessageBox.critical(self, "BlueAway error", tb)

        # -- plan -------------------------------------------------------

        def _current_device(self) -> Optional[core.BtDevice]:
            it = self.devTree.currentItem()
            return it.data(0, Qt.UserRole) if it else None

        def _device_changed(self):
            self.btnAnalyse.setEnabled(self._current_device() is not None)

        def analyse(self):
            dev = self._current_device()
            if not dev or not self.index:
                return
            self._busy(True, f"[~] Analysing {dev.display} "
                             f"({core.pretty_mac(dev.mac)})...")
            self.planTree.clear()
            t = PlanThread(dev, self.index, self.adapters)
            t.log.connect(self._log)
            t.finished_ok.connect(self._plan_done)
            t.failed.connect(self._thread_failed)
            self._threads.append(t)
            t.start()

        def _plan_done(self, plan: core.Plan):
            self.plan = plan
            self.planTree.blockSignals(True)
            self.planTree.clear()

            groups: Dict[str, QTreeWidgetItem] = {}
            counts: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

            for conf in ("HIGH", "MEDIUM", "LOW"):
                g = QTreeWidgetItem(self.planTree, [
                    f"{conf} confidence", "", CONF_BLURB[conf]])
                f = QFont()
                f.setBold(True)
                g.setFont(0, f)
                g.setForeground(0, CONF_COLOR[conf])
                g.setFlags(g.flags() | Qt.ItemIsUserCheckable
                           | Qt.ItemIsAutoTristate)
                g.setCheckState(0, Qt.Unchecked)
                g.setExpanded(conf != "LOW")
                groups[conf] = g

            for ref in plan.references:
                protected = ref.reason.startswith("protected")
                label = ref.record.full
                action = "delete key" if ref.action == "DELETE_KEY" \
                    else f"delete {len(ref.value_names)} value(s)"
                if protected:
                    action = "review only"
                it = QTreeWidgetItem(groups[ref.confidence],
                                     [label, action, ref.reason])
                it.setData(0, Qt.UserRole, ref)
                it.setForeground(1, CONF_COLOR[ref.confidence])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                if protected:
                    it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
                    it.setCheckState(0, Qt.Unchecked)
                else:
                    it.setCheckState(
                        0, Qt.Checked if ref.confidence in ("HIGH", "MEDIUM")
                        else Qt.Unchecked)
                if ref.value_names:
                    it.setToolTip(0, "Values: " + ", ".join(ref.value_names))
                counts[ref.confidence] += 1

            for conf, g in groups.items():
                g.setText(0, f"{conf} confidence  ({counts[conf]})")
                if counts[conf] == 0:
                    g.setHidden(True)

            self.planTree.blockSignals(False)

            ident = len(plan.identity) if plan.identity else 0
            self.planLabel.setText(
                f"References for {plan.device.display} - "
                f"{ident} identifiers discovered over {plan.rounds} expansion "
                f"round(s), {len(plan.references)} references")
            for n in plan.notes:
                self._log(f"[!] {n}")
            self._log(f"[+] Plan ready: {counts['HIGH']} certain, "
                      f"{counts['MEDIUM']} derived, {counts['LOW']} mentions.")
            self.btnReport.setEnabled(True)
            self._busy(False)

        def _item_checked(self, item, column):
            pass  # tristate handled by Qt

        def _checked_refs(self) -> List[core.Reference]:
            out = []
            for i in range(self.planTree.topLevelItemCount()):
                g = self.planTree.topLevelItem(i)
                for j in range(g.childCount()):
                    c = g.child(j)
                    if c.checkState(0) == Qt.Checked and (c.flags() & Qt.ItemIsEnabled):
                        ref = c.data(0, Qt.UserRole)
                        if ref:
                            out.append(ref)
            return out

        # -- execute ----------------------------------------------------

        def remove(self):
            if not self.plan:
                return
            sel = self._checked_refs()
            if not sel:
                QMessageBox.information(self, "Nothing selected",
                                        "Check at least one reference.")
                return
            dry = self.chkDry.isChecked()
            keys = sum(1 for r in sel if r.action == "DELETE_KEY")
            vals = len(sel) - keys

            if not dry:
                if not core.is_admin():
                    QMessageBox.critical(
                        self, "Not elevated",
                        "BlueAway must run as Administrator to modify the "
                        "registry. Restart it elevated.")
                    return
                text = (f"Permanently remove {keys} registry key(s) and edit "
                        f"{vals} key(s)' values for:\n\n"
                        f"    {self.plan.device.display}\n"
                        f"    {core.pretty_mac(self.plan.device.mac)}\n\n"
                        f"A .reg backup is written to:\n{self.backup_dir}\n\n"
                        "Proceed?")
                if QMessageBox.warning(
                        self, "Confirm removal", text,
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No) != QMessageBox.Yes:
                    return

            self._busy(True, f"[~] {'Dry run' if dry else 'Removing'}: "
                             f"{keys} key(s), {vals} value edit(s)...")
            t = ExecThread(self.plan, sel, self.backup_dir, dry,
                           self.chkUnpair.isChecked(), self.chkPnp.isChecked(),
                           self.chkRestart.isChecked())
            t.log.connect(self._log)
            t.finished_ok.connect(self._exec_done)
            t.failed.connect(self._thread_failed)
            self._threads.append(t)
            t.start()

        def _exec_done(self, res: core.ExecResult):
            self._busy(False)
            if res.dry_run:
                self._log("[i] Dry run complete. Uncheck 'Dry run' to apply.")
                return
            msg = (f"Deleted {res.keys_deleted} key(s), removed "
                   f"{res.values_deleted} value(s).\n"
                   f"Failed: {res.keys_failed} key(s), {res.values_failed} "
                   f"value(s).\n\nBackup: {res.backup_path}")
            QMessageBox.information(self, "Removal complete", msg)
            self.start_scan()

        def show_backups(self):
            BackupDialog(self.backup_dir, self).exec_()

        def fix_handsfree_audio(self):
            if not core.is_admin():
                QMessageBox.warning(
                    self, "Not elevated",
                    "Restarting Bluetooth services requires Administrator. "
                    "Restart BlueAway elevated.")
                return
            self.btnFixHfp.setEnabled(False)
            self._log("[~] Restarting Bluetooth Audio Gateway Service "
                      "(no pairing or registry changes)...")
            t = AudioGatewayThread()
            t.log.connect(self._log)
            t.finished_ok.connect(self._hfp_fix_done)
            t.failed.connect(self._thread_failed)
            self._threads.append(t)
            t.start()

        def _hfp_fix_done(self, ok: bool):
            self.btnFixHfp.setEnabled(True)
            if ok:
                self._log("[+] Audio Gateway Service restarted. Check "
                          "Sound settings for the Hands-Free device.")
            else:
                self._log("[-] Restart failed -- see log above.")

        def export_report(self):
            if not self.plan:
                return
            default = os.path.join(
                self.backup_dir,
                f"blueaway_{self.plan.device.mac}.json")
            path, _ = QFileDialog.getSaveFileName(
                self, "Export report", default, "JSON (*.json)")
            if path:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                core.save_report(self.plan, path)
                self._log(f"[+] Report written to {path}")


def run_gui(backup_dir: Optional[str] = None) -> int:
    if not HAVE_QT:
        print("PyQt5 is not installed. pip install PyQt5", file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = BlueAwayWindow(backup_dir=backup_dir)
    win.show()
    return app.exec_()


# ==========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="blueaway", description="Deep Bluetooth device trace remover.")
    ap.add_argument("--list", action="store_true", help="list devices and exit")
    ap.add_argument("--fix-hfp", action="store_true",
                    help="restart the Bluetooth Audio Gateway Service to "
                         "rebuild the Hands-Free audio device (no pairing "
                         "or registry changes) and exit")
    ap.add_argument("--plan", metavar="MAC", help="analyse a device")
    ap.add_argument("--remove", metavar="MAC", help="remove a device")
    ap.add_argument("--yes", action="store_true",
                    help="actually apply --remove (otherwise dry run)")
    ap.add_argument("--json", metavar="FILE", help="write a JSON report")
    ap.add_argument("--backup-dir", metavar="DIR")
    ap.add_argument("--no-elevate", action="store_true",
                    help="do not attempt to relaunch as Administrator")
    args = ap.parse_args()

    cli_mode = bool(args.list or args.plan or args.remove or args.fix_hfp)

    if not core.is_admin() and not args.no_elevate:
        if core.relaunch_as_admin(sys.argv[1:] + ["--no-elevate"]):
            return 0
        print("! Could not elevate; continuing unelevated.", file=sys.stderr)

    if args.fix_hfp:
        return 0 if core.restart_audio_gateway(log=print) else 1

    if cli_mode:
        return run_cli(args)
    return run_gui(args.backup_dir)


if __name__ == "__main__":
    sys.exit(main())
