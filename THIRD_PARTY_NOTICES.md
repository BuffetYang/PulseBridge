# Third-Party Notices

PulseBridge itself is licensed under the MIT License (see `LICENSE`).

The Windows build bundles third-party components. Their licenses and source
locations are listed below. The corresponding license texts are in the
`licenses/` directory next to this file.

## PySide6 / shiboken6 / Qt 6

- Copyright: The Qt Company and contributors.
- License: **LGPL-3.0** (alternatively GPL-3.0 or a commercial Qt license).
- The Qt/PySide6 libraries are shipped as separate DLLs under
  `_internal/PySide6/` and `_internal/`, not statically linked.
- You may replace those DLLs with compatible versions of your own build; see
  <https://doc.qt.io/qt-6/licensing.html> and
  <https://doc.qt.io/qtforpython-6/licenses.html>.
- Source code:
  - Qt: <https://code.qt.io/cgit/qt/>
  - Qt for Python / PySide6: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- License text: `licenses/LGPL-3.0.txt`.

Qt itself includes additional third-party components (for example image
format libraries and ICU). Their notices are part of the Qt distribution;
see <https://doc.qt.io/qt-6/licenses-used-in-qt.html>.

## ZeroConf (python-zeroconf)

- Copyright: python-zeroconf contributors.
- License: **LGPL-2.1**.
- Source: <https://github.com/python-zeroconf/python-zeroconf>
- License text: `licenses/LGPL-2.1.txt`.

## ifaddr

- Copyright: 2016 Pydron.
- License: **MIT**.
- Source: <https://github.com/pydron/ifaddr>
- License text: `licenses/MIT.txt`.

## Segno

- Copyright: 2016–2025 Lars Heuer.
- License: **BSD-3-Clause**.
- Source: <https://github.com/heuer/segno>
- License text: `licenses/BSD-3-Clause.txt`.

## Python

- Copyright: Python Software Foundation and contributors.
- License: **PSF-2.0**.
- Source: <https://www.python.org/>
- License text: `licenses/PSF-2.0.txt`.

## PyInstaller bootloader

- Copyright: PyInstaller contributors.
- License: **GPL-2.0 with the PyInstaller exception**, which permits
  distributing bundled applications under their own terms.
- Source: <https://github.com/pyinstaller/pyinstaller>
- License text: `licenses/PyInstaller.txt`.

## packaging

- Copyright: packaging contributors.
- License: **Apache-2.0** (or BSD-2-Clause, at your option).
- Source: <https://github.com/pypa/packaging>
- License text: `licenses/Apache-2.0.txt`.

## SQLite

- SQLite is in the public domain.
- Source: <https://www.sqlite.org/>

## Notes for redistributors

- Keep `THIRD_PARTY_NOTICES.md` and the `licenses/` directory together with
  `PulseBridge.exe` and `_internal/`.
- If you modify Qt/PySide6 or replace its DLLs, you are responsible for
  complying with the LGPL, including providing the corresponding source.
- This notice is informational and is not legal advice.
