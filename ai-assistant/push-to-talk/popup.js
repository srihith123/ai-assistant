// popup.js

const screenshotBtn = document.getElementById('screenshotBtn');
const stopBtn = document.getElementById('stopBtn');
const pushToTalkBtn = document.getElementById('pushToTalkBtn');
const previewImg = document.getElementById('screenshotPreview');
const statusMsg = document.getElementById('statusMessage');

let isProcessing = false; // Track if AI is active
let isMicMuted = true; // Start muted
let pttActive = false; // Track if PTT button is currently held

// --- Event Listeners ---

screenshotBtn.addEventListener('click', () => {
    if (isProcessing) return; // Prevent multiple clicks if already processing
    
    console.log("Popup: Screenshot button clicked");
    statusMsg.textContent = "Select area on page...";
    previewImg.style.display = 'none'; // Hide previous preview
    screenshotBtn.disabled = true; // Disable button while injecting

    // Send message to background script to start screenshot process
    chrome.runtime.sendMessage({ type: "start_screenshot" }, (response) => {
        screenshotBtn.disabled = false; // Re-enable button
        if (chrome.runtime.lastError) {
            console.error("Popup Error sending start:", chrome.runtime.lastError.message);
            statusMsg.textContent = `Error: ${chrome.runtime.lastError.message}`;
        } else if (response && response.success) {
            console.log("Popup: Start message sent successfully.");
            statusMsg.textContent = "Draw selection box on page.";
            // Close the popup after initiating selection
            window.close();
        } else {
            console.error("Popup: Failed to initiate screenshot.", response);
            statusMsg.textContent = `Error: ${response?.error || 'Failed to start'}`;
        }
    });
});

stopBtn.addEventListener('click', () => {
    console.log("Popup: Stop button clicked");
    statusMsg.textContent = "Stopping AI interaction...";
    stopBtn.disabled = true;
    chrome.runtime.sendMessage({ type: "stop_native_host" }, (response) => {
        stopBtn.disabled = false;
        if (chrome.runtime.lastError) {
            console.error("Popup Error sending stop:", chrome.runtime.lastError.message);
            statusMsg.textContent = `Error stopping: ${chrome.runtime.lastError.message}`;
        } else if (response && response.success) {
            console.log("Popup: Stop message sent.");
            statusMsg.textContent = "AI stopped. Ready for new screenshot.";
            isProcessing = false;
            updateUI();
        } else {
             console.error("Popup: Failed to stop AI.", response);
             statusMsg.textContent = `Error: ${response?.error || 'Stop failed'}`;
        }
    });
});

// Push-to-Talk Listeners
pushToTalkBtn.addEventListener('mousedown', () => {
    console.log("PTT mousedown - Current state:", { isProcessing, pttActive });
    if (!isProcessing || pttActive) return; // Only work if AI is active and not already held
    console.log("Popup: Push-to-talk pressed (unmuting)");
    pttActive = true;
    console.log(`PTT mousedown: pttActive set to ${pttActive}`);
    isMicMuted = false;
    pushToTalkBtn.textContent = "Listening..."; // Indicate active state
    chrome.runtime.sendMessage({ type: "unmute_mic" }, (response) => {
        if (chrome.runtime.lastError) {
            console.error("Popup Error sending unmute:", chrome.runtime.lastError.message);
            // Handle error, maybe revert state?
        } else {
            console.log("Popup: Unmute message sent.");
        }
    });
});

pushToTalkBtn.addEventListener('mouseup', () => {
    console.log("PTT mouseup - Current state:", { isProcessing, pttActive });
    if (!isProcessing || !pttActive) return; // Only work if AI active and button was held
    console.log("Popup: Push-to-talk released (muting)");
    pttActive = false;
    console.log(`PTT mouseup: pttActive set to ${pttActive}`);
    isMicMuted = true;
    pushToTalkBtn.textContent = "Hold to Talk"; // Reset text
    chrome.runtime.sendMessage({ type: "mute_mic" }, (response) => {
         if (chrome.runtime.lastError) {
            console.error("Popup Error sending mute:", chrome.runtime.lastError.message);
            // Handle error
        } else {
            console.log("Popup: Mute message sent.");
        }
    });
});

// Optional: Handle mouse leaving the button while pressed
pushToTalkBtn.addEventListener('mouseleave', () => {
    console.log(`PTT mouseleave: pttActive=${pttActive}`);
    if (pttActive) { // If mouse leaves while button is held
        console.log("PTT mouseleave: Simulating mouseup because pttActive is true.");
        pushToTalkBtn.dispatchEvent(new MouseEvent('mouseup')); // Simulate mouseup
    }
});

// --- Update UI Function ---

function updateUI() {
    if (isProcessing) {
        screenshotBtn.style.display = 'none';
        stopBtn.style.display = 'inline-block';
        pushToTalkBtn.style.display = 'inline-block'; // Show PTT button
        pushToTalkBtn.disabled = false;
        // Reset PTT button text/state if AI was just started
        pushToTalkBtn.textContent = "Hold to Talk";
        isMicMuted = true; // Ensure mic starts muted when AI starts
        pttActive = false;
    } else {
        screenshotBtn.style.display = 'inline-block';
        stopBtn.style.display = 'none';
        pushToTalkBtn.style.display = 'none'; // Hide PTT button
        pushToTalkBtn.disabled = true;
        previewImg.style.display = 'none';
        // statusMsg.textContent = "Ready for screenshot."; // Reset status or keep last status?
    }
}

// --- Listen for messages from background ---

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log("Popup received message:", request.type);
    if (request.type === "screenshot_taken") {
        console.log("Popup: Screenshot taken, displaying preview.");
        previewImg.src = request.imageData; 
        previewImg.style.display = 'block';
        statusMsg.textContent = "Image sent to AI Tutor.";
        isProcessing = true;
        updateUI();
        sendResponse({ success: true });
    } else if (request.type === "native_host_disconnected") {
        console.log("Popup: Native host disconnected.")
        statusMsg.textContent = "AI session ended or disconnected.";
        isProcessing = false;
        updateUI();
        sendResponse({ success: true });
    } else if (request.type === "native_host_error") {
         console.error("Popup: Received native host error:", request.error);
         statusMsg.textContent = `Connection Error: ${request.error}`;
         isProcessing = false;
         updateUI();
         sendResponse({ success: true });
    }
    // Keep listener active for other potential messages
    return true; 
});

// --- Initial State ---

// Check initial state when popup opens (e.g., is AI already running?)
// This requires the background script to maintain state.
chrome.runtime.sendMessage({ type: "get_status" }, (response) => {
     if (chrome.runtime.lastError) {
         console.warn("Popup: Error getting initial status:", chrome.runtime.lastError.message);
         // Assume not processing if error
         isProcessing = false;
     } else if (response && response.isProcessing) {
         console.log("Popup: AI is currently processing.");
         isProcessing = true;
         statusMsg.textContent = "AI is currently active.";
         if (response.lastImageData) {
             previewImg.src = response.lastImageData;
             previewImg.style.display = 'block';
         }
     } else {
         console.log("Popup: AI is not currently processing.");
         isProcessing = false;
         // statusMsg.textContent = "Ready for screenshot."; // Set initial text
     }
     updateUI(); // Set initial button visibility
});