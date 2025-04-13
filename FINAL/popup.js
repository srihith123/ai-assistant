// popup.js

const screenshotBtn = document.getElementById('screenshotBtn');
const stopBtn = document.getElementById('stopBtn');
const nextBtn = document.getElementById('nextBtn');
const pushToTalkBtn = document.getElementById('pushToTalkBtn');
const previewImg = document.getElementById('screenshotPreview');
const statusMsg = document.getElementById('statusMessage');

let isProcessing = false;
let isMicMuted = true;
let pttActive = false;
let reconnectAttempted = false;

// --- Event Listeners ---

screenshotBtn.addEventListener('click', () => {
    if (isProcessing) return;
    
    console.log("Popup: Screenshot button clicked");
    statusMsg.textContent = "Select area on page...";
    previewImg.style.display = 'none';
    screenshotBtn.disabled = true;
    reconnectAttempted = false;

    chrome.runtime.sendMessage({ type: "start_screenshot" }, (response) => {
        screenshotBtn.disabled = false;
        if (chrome.runtime.lastError) {
            console.error("Popup Error sending start:", chrome.runtime.lastError.message);
            statusMsg.textContent = `Error: ${chrome.runtime.lastError.message}`;
        } else if (response && response.success) {
            console.log("Popup: Start message sent successfully.");
            statusMsg.textContent = "Draw selection box on page.";
            window.close();
        } else {
            console.error("Popup: Failed to initiate screenshot.", response);
            statusMsg.textContent = `Error: ${response?.error || 'Failed to start'}`;
        }
    });
});

nextBtn.addEventListener('click', () => {
    console.log("Popup: Next Question button clicked");
    statusMsg.textContent = "Ready for next question...";
    
    // Send interrupt signal to stop current audio playback
    chrome.runtime.sendMessage({ type: "interrupt_playback" }, () => {
        // Reset state but keep connection
        isProcessing = false;
        isMicMuted = true;
        pttActive = false;
        previewImg.style.display = 'none';
        
        // Update UI for new question
        updateUI();
        
        // Notify background to reset state but maintain connection
        chrome.runtime.sendMessage({ type: "reset_state" }, (response) => {
            if (chrome.runtime.lastError) {
                console.error("Popup Error resetting state:", chrome.runtime.lastError.message);
                statusMsg.textContent = `Error: ${chrome.runtime.lastError.message}`;
            } else {
                statusMsg.textContent = "Ready for new screenshot.";
                console.log("State reset successful");
            }
        });
    });
});

stopBtn.addEventListener('click', () => {
    console.log("Popup: Stop button clicked");
    statusMsg.textContent = "Ending session...";
    stopBtn.disabled = true;
    chrome.runtime.sendMessage({ type: "stop_native_host" }, (response) => {
        stopBtn.disabled = false;
        if (chrome.runtime.lastError) {
            console.error("Popup Error sending stop:", chrome.runtime.lastError.message);
            statusMsg.textContent = `Error ending session: ${chrome.runtime.lastError.message}`;
        } else if (response && response.success) {
            console.log("Popup: Stop message sent.");
            statusMsg.textContent = "Session ended. Extension will close.";
            isProcessing = false;
            setTimeout(() => window.close(), 1500); // Close popup after showing message
        } else {
            console.error("Popup: Failed to stop AI.", response);
            statusMsg.textContent = `Error: ${response?.error || 'Failed to end session'}`;
        }
    });
});

// Push-to-Talk Listeners
pushToTalkBtn.addEventListener('mousedown', () => {
    if (!isProcessing || pttActive) return;
    console.log("Popup: Push-to-talk pressed (unmuting)");
    pttActive = true;
    isMicMuted = false;
    pushToTalkBtn.textContent = "Listening...";
    chrome.runtime.sendMessage({ type: "unmute_mic" });
});

pushToTalkBtn.addEventListener('mouseup', () => {
    if (!isProcessing || !pttActive) return;
    console.log("Popup: Push-to-talk released (muting)");
    pttActive = false;
    isMicMuted = true;
    pushToTalkBtn.textContent = "Hold to Talk";
    chrome.runtime.sendMessage({ type: "mute_mic" });
});

pushToTalkBtn.addEventListener('mouseleave', () => {
    if (pttActive) {
        pushToTalkBtn.dispatchEvent(new MouseEvent('mouseup'));
    }
});

function updateUI() {
    if (isProcessing) {
        screenshotBtn.style.display = 'none';
        nextBtn.style.display = 'inline-block';
        stopBtn.style.display = 'inline-block';
        pushToTalkBtn.style.display = 'inline-block';
        pushToTalkBtn.disabled = false;
        pushToTalkBtn.textContent = "Hold to Talk";
        isMicMuted = true;
        pttActive = false;
    } else {
        screenshotBtn.style.display = 'inline-block';
        nextBtn.style.display = 'none';
        stopBtn.style.display = 'none';
        pushToTalkBtn.style.display = 'none';
        pushToTalkBtn.disabled = true;
        previewImg.style.display = 'none';
    }
}

// --- Listen for messages from background ---

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log("Popup received message:", request.type);
    
    switch (request.type) {
        case "screenshot_taken":
            console.log("Popup: Screenshot taken, displaying preview.");
            previewImg.src = request.imageData;
            previewImg.style.display = 'block';
            statusMsg.textContent = "Image sent to AI Tutor.";
            isProcessing = true;
            updateUI();
            sendResponse({ success: true });
            break;
            
        case "native_host_disconnected":
            if (!reconnectAttempted) {
                console.log("Popup: Native host disconnected, attempting reconnect...");
                reconnectAttempted = true;
                chrome.runtime.sendMessage({ type: "reconnect_native_host" }, (response) => {
                    if (response && response.success) {
                        statusMsg.textContent = "Reconnected successfully.";
                    } else {
                        handleDisconnect("Reconnection failed");
                    }
                });
            } else {
                handleDisconnect("Connection lost");
            }
            break;
            
        case "native_host_error":
            console.error("Popup: Received native host error:", request.error);
            handleDisconnect(request.error);
            break;
    }
    return true;
});

function handleDisconnect(error) {
    statusMsg.textContent = `Error: ${error}. Please try again.`;
    isProcessing = false;
    updateUI();
}

// --- Initial State ---
chrome.runtime.sendMessage({ type: "get_status" }, (response) => {
    if (chrome.runtime.lastError) {
        console.warn("Popup: Error getting initial status:", chrome.runtime.lastError.message);
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
    }
    updateUI();
});