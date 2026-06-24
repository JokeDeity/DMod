
<center>DMod
<img width="1240" height="407" alt="Untitled" src="https://github.com/user-attachments/assets/3a7195c5-5b30-487a-bf3a-369bd8220f42" /></center>
NEW FEATURE:  Double-click Hide Desktop Icons:  Double-click on your desktop to hide all the icons.

NEW FEATURE:  Unsnag:  Unsnag your cursor from the corners on multiple monitor setups.

NEW FEATURE:  Monitor Wrap:  Your cursor goes off the edge of one side and enters the other, again helpful for mulitple monitor setups.

NEW FEATURE:  Cursorlock:  Lock your cursor to the active window with a hotkey.  

NEW FEATURE:  Always on Top toggle:  Turn any active window into always on top (requires run as admin for elevated windows).

A lightweight desktop utility to dim distractions. It lets you draw one or more focus zones on your screen, dimming everything else with customizable "veil" effects.
Core Features

	NEW FEATURE:  Multiple Shape Tools:  rectangle, circle, ellipses, diamond, and triangle.

    Multi-Zone Focus: Define one or multiple areas to stay visible while the rest of the screen is obscured.

    Custom Overlays:

        Standard: Solid colors.

        Dynamic: GPU-efficient atmospheric effects.

        GIFs:  Some fun and some ambient.

        Custom: Support for your own animated GIFs or veils presuming you can do some light coding to
		edit the python script.

    Audio Cues: Sound effects for activation, pausing, and clearing.

    GUI Settings: Sits comfortably in the system tray out of the way, now with a nice GUI for setting 
	everything as you like.
	

How to Use

    Version: 
		  If you are using the V1.5 release you just need to download and run, but let me know if sounds don't work 
		  or anything seems broken.  ((This is the version I suggest to use.))
	
          If you are using the V1.0 .exe from the archive in the releases section you just need to extract 
		  everything to one location and then launch the .exe.
    
          If you download the files from the repository you will have to run the python script 
		  (dmod.py) from either CMD Prompt or Powershell:
				CD into the folder
				"python dmod.py"



    Hotkeys: Set them as you would like in the settings window, there's one for setting the veil, one for pausing 
	it,	one to toggle cursorlock, and one to toggle always on top.

    Activate: Hold your Veil hotkey to start selecting areas for the , or press it once to cover the 
	entire screen(s).

    Select: Click and drag to create one or more transparent focus rectangles.

    Deploy: Release your hotkey to lock the selection and fade in the veil.

    Toggle: Use your pause hotkey to pause and resume the effect with the selection you have.

    Configure: Right-click the system tray icon to adjust opacity, colors, timing, veil types and more in the 
	settings window.

Technical Details

    Built With: Python, PyQt5, Pygame, and Pynput.

    Configuration: Saves all preferences (opacity, colors, delays) automatically via QSettings.

    Deployment: Easily bundled into a standalone Windows executable using PyInstaller.  The 
	releases section contains an archive with a prebuilt .exe and the necessary files for running it.


*the energy veil in the repository version of this is lower quality because github doesn't allow files larger than 25mb.
