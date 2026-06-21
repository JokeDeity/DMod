TheaterMode

A lightweight desktop utility to dim distractions. It lets you draw one or more focus zones on your screen, dimming everything else with customizable "veil" effects.
Core Features

    Multi-Zone Focus: Define multiple areas to stay visible while the rest of the screen is obscured.

    Custom Overlays:

        Standard: Solid colors.

        Dynamic: GPU-efficient atmospheric effects.

        GIFs:  Some fun and some ambient.

        Custom: Support for your own animated GIFs or veils presuming you can do some light coding to edit the python script.

    Audio Cues: Sound effects for activation, pausing, and clearing.

    Tray Control: Manage settings via the system tray without taskbar clutter.

How to Use

    Version: If you download the files from the repository you will have to run the python script (dmod.py) from either CMD Prompt or Powershell:
        CD into the folder
        "python dmod.py"

      If You are using the .exe from the archive in the releases section you just need to extract everything to one location and then launch the .exe.

    Hotkeys: Set them as you would like, right now you'll have to enter them manually, but the plan in next version is to just press the key you want.

    Activate: Hold your activate hotkey to start selecting areas, or press it once to cover the entire screen(s).

    Select: Click and drag to create one or more transparent focus rectangles.

    Deploy: Release your hotkey to lock the selection and fade in the veil.

    Toggle: Use your pause hotkey to pause and resume the effect with the selection you have.

    Configure: Right-click the system tray icon to adjust opacity, colors, timing, and veil types.

Technical Details

    Built With: Python, PyQt5, Pygame, and Pynput.

    Configuration: Saves all preferences (opacity, colors, delays) automatically via QSettings.

    Deployment: Easily bundled into a standalone Windows executable using PyInstaller.  The releases section contains an archive with a prebuilt .exe and the necessary files for running it.
