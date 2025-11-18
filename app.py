import os
import wave
import struct
import streamlit as st
from pydub import AudioSegment
import tempfile
import subprocess
from io import BytesIO
# 🚨 NEW: Import NumPy for signal processing (DSSS)
import numpy as np 

# --- Configuration & Setup ---
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- DSSS Utility Functions ---

def generate_pn_sequence(chip_rate, duration_samples):
    """
    Generates a simple Pseudo-Noise (PN) sequence (Spreading Code).
    A chip_rate of 1 (every sample) is used for simplicity.
    In a real system, this sequence is often based on Linear Feedback Shift Registers (LFSRs).
    """
    # Use a fixed seed for reproducibility, crucial for extraction
    np.random.seed(42) 
    # Generate random +1 or -1 values, based on the total number of samples
    # We use samples to simplify synchronization and assume chip_rate = sample_rate
    return (np.random.randint(0, 2, duration_samples) * 2 - 1).astype(np.int16)

# --- Watermarking Functions (DSSS on WAV) ---

# Watermarking function (REPLACED LSB with DSSS)
def embed_watermark_dsss(input_wav, watermark_text, output_wav):
    """Embeds a watermark (user ID) using a basic Direct Sequence Spread Spectrum (DSSS) method."""
    
    with wave.open(input_wav, "rb") as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)
        sample_width = params.sampwidth
        nchannels = params.nchannels
        frame_rate = params.framerate

    # Unpack frames into a NumPy array of 16-bit integers
    # 'h' for 16-bit (2 bytes), '<' for little-endian
    samples = np.frombuffer(frames, dtype=np.int16)

    # 1. Prepare Watermark Data (Binary)
    # For robust DSSS, we embed a short, repeatable sequence. 
    # We will embed a fixed 16-bit binary signature + the user ID.
    signature_bit = 1 # A simple bit to verify the presence of the watermark
    user_id_bits = np.array([int(b) * 2 - 1 for b in format(int(watermark_text), '08b')]) # Convert 0/1 to -1/+1
    
    # Simple Watermark Payload: [Signature Bit (1) + User ID (8 bits)]
    payload = np.concatenate([[signature_bit * 2 - 1], user_id_bits])
    
    # 2. Generate Spreading Code (PN Sequence)
    # Use the full length of the audio for the spreading code
    pn_sequence = generate_pn_sequence(frame_rate, len(samples)) 
    
    # 3. Spread the Watermark Data
    # The spreading rate is the ratio of audio length to watermark length (DSSS processing gain)
    spreading_factor = int(np.floor(len(samples) / len(payload)))
    
    if spreading_factor < 100: # Arbitrary minimum required gain
        raise ValueError("Audio is too short for meaningful DSSS spreading.")

    watermark_signal = np.zeros_like(samples, dtype=np.float64)

    # Multiply each payload bit by a segment of the PN sequence
    for i, data_bit in enumerate(payload):
        start_index = i * spreading_factor
        end_index = (i + 1) * spreading_factor
        
        # Multiply the PN sequence segment by the data bit (+1 or -1)
        segment_length = min(spreading_factor, len(samples) - start_index)
        watermark_signal[start_index:end_index] = (pn_sequence[start_index:end_index] * data_bit)

    # 4. Scale and Embed
    # The embedding strength (alpha) controls robustness vs. imperceptibility.
    # A small factor (e.g., 0.01) keeps the watermark imperceptible.
    alpha = 0.01 
    watermarked_samples = samples + (watermark_signal * alpha * np.max(np.abs(samples)))
    
    # Clip samples to the 16-bit range to prevent overflow noise
    watermarked_samples = np.clip(watermarked_samples, -32768, 32767).astype(np.int16)
    
    # 5. Pack and Write to WAV
    new_frames = watermarked_samples.tobytes()

    with wave.open(output_wav, "wb") as wav_out:
        wav_out.setparams(params)
        wav_out.writeframes(new_frames)

    return output_wav

# --- FFmpeg Utilities (UNCHANGED) ---

def extract_audio_ffmpeg(video_path, output_wav_path):
    """Extracts audio from video to a temporary WAV file."""
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        output_wav_path
    ], check=True, capture_output=True)

def insert_audio_ffmpeg(video_path, audio_path, output_video_path):
    """Re-inserts the watermarked audio into the original video."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        output_video_path
    ], check=True, capture_output=True)

# --- Core Processing Logic (MODIFIED to call DSSS) ---

@st.cache_data
def process_video_to_bytes(video_path, user_id):
    """
    Processes the video and returns the processed video content as bytes.
    """
    st.info(f"Processing video for user ID: {user_id} using DSSS...")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_audio_wav = os.path.join(temp_dir, "temp_audio.wav")
        watermarked_audio_wav = os.path.join(temp_dir, "watermarked_audio.wav")
        watermarked_audio_mp3 = os.path.join(temp_dir, "watermarked_audio.mp3")
        processed_video_path = os.path.join(temp_dir, "processed_video.mp4")

        try:
            # 1. Extract audio
            extract_audio_ffmpeg(video_path, temp_audio_wav)

            # 2. Embed watermark into WAV using DSSS (CHANGED HERE)
            embed_watermark_dsss(temp_audio_wav, str(user_id), watermarked_audio_wav)

            # 3. Convert watermarked WAV to MP3 
            sound = AudioSegment.from_wav(watermarked_audio_wav)
            sound.export(watermarked_audio_mp3, format="mp3")

            # 4. Re-insert audio into video
            insert_audio_ffmpeg(video_path, watermarked_audio_mp3, processed_video_path)

            # 5. Read the final video into memory
            with open(processed_video_path, "rb") as f:
                video_bytes = f.read()
            
            st.success("Video processing complete!")
            return video_bytes
        
        except subprocess.CalledProcessError as e:
            st.error(f"FFmpeg command failed. Is FFmpeg installed? Error: {e.stderr.decode()}")
            return None
        except Exception as e:
            st.error(f"An error occurred during processing: {e}")
            return None

# --- Streamlit App (UNCHANGED) ---

def main():
    st.title("Simple OTT Video App with DSSS Audio Watermarking")

    # Initialize Session State
    if 'users' not in st.session_state:
        st.session_state.users = {}
    if 'logged_in_user' not in st.session_state:
        st.session_state.logged_in_user = None

    # Sidebar for login/registration
    with st.sidebar:
        st.header("🔑 Authentication")
        if st.session_state.logged_in_user:
            st.write(f"Logged in as: **{st.session_state.logged_in_user}** (ID: {st.session_state.users[st.session_state.logged_in_user]['id']})")
            if st.button("Logout"):
                st.session_state.logged_in_user = None
                st.rerun() # Use st.rerun() for instant UI refresh on state change
        else:
            auth_mode = st.radio("Choose:", ["Login", "Register"], key="auth_mode")
            username = st.text_input("Username", key="username_input")
            password = st.text_input("Password", type="password", key="password_input")
            
            if st.button("Submit"):
                if auth_mode == "Register":
                    if username in st.session_state.users:
                        st.error("Username already exists")
                    else:
                        user_id = len(st.session_state.users) + 1
                        st.session_state.users[username] = {'password': password, 'id': user_id}
                        st.success("Registered successfully! Please login.")
                elif auth_mode == "Login":
                    if username in st.session_state.users and st.session_state.users[username]['password'] == password:
                        st.session_state.logged_in_user = username
                        st.success("Logged in!")
                        st.rerun() # Use st.rerun() for instant UI refresh on state change
                    else:
                        st.error("Invalid credentials")

    if not st.session_state.logged_in_user:
        st.warning("Please log in to access the video features.")
        return

    # User is logged in
    user_id = st.session_state.users[st.session_state.logged_in_user]['id']

    # --- Upload Section ---
    st.header("⬆️ Upload Video (Admin Mockup)")
    uploaded_file = st.file_uploader("Choose a video file", type=list(ALLOWED_EXTENSIONS))
    
    if uploaded_file:
        if st.button("Save Upload"):
            for f in os.listdir(UPLOAD_FOLDER):
                os.remove(os.path.join(UPLOAD_FOLDER, f))

            filename = uploaded_file.name
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.session_state.last_uploaded_video = filename
            st.success(f"Uploaded and saved **{filename}**")
            st.rerun()

    # --- List and Download Videos ---
    st.header("🎬 Available Videos for Download")
    videos = [f for f in os.listdir(UPLOAD_FOLDER) if f.split('.')[-1].lower() in ALLOWED_EXTENSIONS]

    if videos:
        for video in videos:
            video_path = os.path.join(UPLOAD_FOLDER, video)
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{video}**")

            with col2:
                download_key = f"download_{video}_{user_id}"

                if st.button(f"Process & Get '{video}'", key=f"process_btn_{video}"):
                    video_bytes = process_video_to_bytes(video_path, user_id)
                    
                    if video_bytes:
                        st.session_state[download_key] = video_bytes
                        st.success(f"Processing complete. Ready for download: watermarked_{video}")
                    else:
                        st.error("Failed to process video. See error details above.")

                if download_key in st.session_state:
                    st.download_button(
                        label="Download Processed Video",
                        data=st.session_state[download_key],
                        file_name=f"watermarked_{video}",
                        mime="video/mp4",
                        key=f"final_download_{video}"
                    )
    else:
        st.info("No videos uploaded yet.")

if __name__ == "__main__":
    main()
