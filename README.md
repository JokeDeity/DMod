
<center>
	DMod
<img width="1400" height="547" alt="image" src="https://github.com/user-attachments/assets/c7e93097-c325-44b4-960d-9c8ff8dbafa2" />
<img width="1400" height="547" alt="image" src="https://github.com/user-attachments/assets/2f5e033b-ffa6-44bc-9acb-f4939ff4ced0" />
<img width="1400" height="547" alt="image" src="https://github.com/user-attachments/assets/dbe66cb3-7679-427c-b61d-235f17b28e41" />
</center>

**NEW FEATURES:  Lots of new features are currently contained to the source files only and have not been compiled to a new update, you can download the source files and launch with the .vbs file for now while kinks are worked out.

NEW FEATURE:  Bluetooth device manager subprogram.  This launches a small separate utility that lets you remove stubborn bluetooth devices that Windows fails to remove on it's own, also makes a backup in case you remove something by accident.

NEW FEATURE:  Hotkey clear buttons:  Not sure if this should be called a feature and definitely should have been there from the start, but you can clear hotkeys you don't want to use now.

New feature:  Screensaver mode:  Now you can set a timer and after that much idle time it will automatically kick in a fullscreen veil, just need to move the mouse around or click to bring it back.

New feature:  Veil Mode Auto-Dim:  This mode will automatically make whatever window is active be visible while everything else (with some exceptions and kinks) should be covered by the veil.

*Double-click Hide Desktop Icons:  Double-click on your desktop to hide all the icons.

*Unsnag:  Unsnag your cursor from the corners on multiple monitor setups.

*Monitor Wrap:  Your cursor goes off the edge of one side and enters the other, again helpful for mulitple monitor setups.

*Cursorlock:  Lock your cursor to the active window with a hotkey.  

*Always on Top toggle:  Turn any active window into always on top (requires run as admin for elevated windows).

A lightweight desktop utility to dim distractions. It lets you draw one or more focus zones on your screen, dimming everything else with customizable "veil" effects.
Core Features

	Multiple Shape Tools:  Rectangle, circle, ellipses, diamond, and triangle.

    Multi-Zone Focus: Define one or multiple areas to stay visible while the rest of the screen is obscured.

    Custom Overlays:

        Standard: Solid colors.

        Dynamic: GPU-efficient atmospheric effects and plenty of them.

        GIFs:  Some fun .gifs, these are either on the chopping block or going to get more added, not sure yet.

        Custom: Support for your own animated GIFs or veils presuming you can do some light coding to
		edit the python script of the repository version.

		Settings:  Change the colors of various veils and the opacity as well as how fast they fade in and out.

    Audio Cues: Sound effects for activation, pausing, and clearing.

    GUI Settings: Sits comfortably in the system tray out of the way, now with a nice GUI for setting 
	everything as you like.
	
How to Use

    Version: 
		  If you are using the V1.5 release or newer you just need to download and run, but let me know if sounds don't work 
		  or anything seems broken.  ((This is the version I suggest to use.))
	
          If you are using the V1.0 .exe from the archive in the releases section you just need to extract 
		  everything to one location and then launch the .exe.
    
          If you download the files from the repository you will want to run the .vbs file or make a shortcut to it.

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

    Configuration: Saves all preferences (opacity, colors, delays) automatically via QSettings.

    Deployment: Easily bundled into a standalone Windows executable using PyInstaller.  The 
	releases section contains an archive with a prebuilt .exe and the necessary files for running it.
