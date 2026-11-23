(function () {
  const qrImage = document.getElementById("qr-image");
  if (qrImage && window.sessionQrRefresh) {
    const status = document.getElementById("qr-status");

    async function refreshQr() {
      try {
        const response = await fetch(window.qrRefreshUrl, {
          headers: { Accept: "application/json" },
          cache: "no-store"
        });
        if (!response.ok) {
          throw new Error("Could not check the attendance session.");
        }
        const result = await response.json();
        if (!result.active) {
          status.textContent = "This session is closed.";
          status.className = "notice error";
          return;
        }
        if (qrImage.dataset.expiresAt !== result.token_expires_at) {
          qrImage.src = window.qrImageUrl + "?updated=" + Date.now();
          qrImage.dataset.expiresAt = result.token_expires_at;
        }
        status.textContent = "QR code is active and refreshes every 30 seconds.";
        status.className = "notice success";
      } catch (error) {
        status.textContent = error.message;
        status.className = "notice error";
      }
    }

    window.setInterval(refreshQr, 1000);
    refreshQr();
  }

  const readerElement = document.getElementById("reader");
  if (!readerElement) {
    return;
  }

  const message = document.getElementById("scan-message");
  const startButton = document.getElementById("start-scan");
  const stopButton = document.getElementById("stop-scan");
  let scanner;
  let submitting = false;

  function showMessage(text, kind) {
    message.textContent = text;
    message.className = "notice " + (kind || "");
  }

  async function submitToken(token) {
    if (!token || submitting) {
      return;
    }
    submitting = true;
    showMessage("QR code found. Checking attendance…", "");
    try {
      const response = await fetch(window.markAttendanceUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ token: token })
      });
      const result = await response.json();
      showMessage(result.message, result.success ? "success" : "error");
      if (scanner && scanner.isScanning) {
        await scanner.stop();
      }
    } catch (error) {
      showMessage("Could not contact the server. Check your connection and try again.", "error");
      submitting = false;
    }
  }

  function tokenFromQr(value) {
    try {
      const parsed = new URL(value);
      return parsed.searchParams.get("token") || "";
    } catch (_error) {
      return value;
    }
  }

  async function startScanner() {
    if (typeof Html5Qrcode === "undefined") {
      showMessage("The scanner library did not load. Check your internet connection and reload.", "error");
      return;
    }
    try {
      submitting = false;
      if (!scanner) {
        scanner = new Html5Qrcode("reader");
      }
      showMessage("Requesting camera access…", "");
      await scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 240, height: 240 } },
        function (decodedText) {
          submitToken(tokenFromQr(decodedText));
        },
        function () {}
      );
      showMessage("Camera is ready. Point it at the QR code.", "success");
    } catch (_error) {
      showMessage("Camera could not start. Allow camera access and open this page over HTTPS (or localhost).", "error");
    }
  }

  startButton.addEventListener("click", startScanner);
  stopButton.addEventListener("click", async function () {
    if (scanner && scanner.isScanning) {
      await scanner.stop();
      showMessage("Camera stopped.", "");
    }
  });

  startScanner();
})();
