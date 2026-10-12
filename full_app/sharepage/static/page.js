"use strict";
const player = document.getElementById("montage");
document.querySelectorAll("[data-start]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const seek = () => {
      player.currentTime = Math.min(Number(link.dataset.start), player.duration || Infinity);
      player.play().catch(() => {});
    };
    if (player.readyState >= 1) seek();
    else {
      player.addEventListener("loadedmetadata", seek, { once: true });
      player.load();
    }
  });
});
const reactions = document.getElementById("reactions");
const buttons = [...reactions.querySelectorAll("button")];
const status = document.getElementById("reaction-status");
buttons.forEach((button) => {
  button.disabled = false;
  button.addEventListener("click", async () => {
    buttons.forEach((item) => { item.disabled = true; });
    status.textContent = "Sending…";
    try {
      const response = await fetch(reactions.dataset.url, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Sharepage-Reaction": "1" },
        body: JSON.stringify({ emoji: button.dataset.emoji }),
      });
      if (!response.ok) throw new Error("Reaction failed");
      const data = await response.json();
      buttons.forEach((item) => { item.querySelector(".count").textContent = data.counts[item.dataset.emoji]; });
      status.textContent = "Reaction sent!";
    } catch {
      status.textContent = "Could not send your reaction. The link may have expired. Try again.";
    } finally {
      buttons.forEach((item) => { item.disabled = false; });
    }
  });
});
