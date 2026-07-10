import os
from pydub import AudioSegment

def convert_audio_to_opus(source_directory, output_directory):
    """
    Converts .mp3 and .wav files to .ogg (Opus) to optimize size and quality.
    """
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Supported formats to look for
    valid_formats = ('.mp3', '.wav')

    for filename in os.listdir(source_directory):
        if filename.lower().endswith(valid_formats):
            file_path = os.path.join(source_directory, filename)
            
            # Load the audio file
            print(f"Processing: {filename}")
            audio = AudioSegment.from_file(file_path)

            # Define new filename
            base_name = os.path.splitext(filename)[0]
            output_path = os.path.join(output_directory, f"{base_name}.ogg")

            # Export as ogg with opus codec
            # 'bitrate' can be adjusted (e.g., '128k' is usually transparent for music)
            audio.export(output_path, format="ogg", codec="libopus", bitrate="128k")
            print(f"Saved to: {output_path}")

# --- Execution ---
if __name__ == "__main__":
    # Change these paths to your project directories
    source_dir = "./audio_files" 
    target_dir = "./audio_files_converted"
    
    convert_audio_to_opus(source_dir, target_dir)