// Adds a "Show password" / "Hide password" toggle to password fields on the
// sign-in and create-account pages, so people can see what they typed (or
// what a voice-typing/dictation keyboard put in the field) instead of only
// seeing dots.
(function () {
  function setupToggle(button) {
    var targetId = button.getAttribute("data-target");
    var input = document.getElementById(targetId);
    if (!input) return;

    button.addEventListener("click", function () {
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.textContent = showing ? "Show password" : "Hide password";
      button.setAttribute("aria-pressed", showing ? "false" : "true");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var buttons = document.querySelectorAll(".password-toggle");
    for (var i = 0; i < buttons.length; i++) {
      setupToggle(buttons[i]);
    }
  });
})();
