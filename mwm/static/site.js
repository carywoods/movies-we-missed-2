// Carousel controls: buttons carry data-carousel="<track id>" and data-dir.
// The track itself is a native horizontal scroller, so touch/swipe and
// trackpads work without JavaScript; these buttons just page it along.
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-carousel]");
  if (!button) return;
  var track = document.getElementById(button.getAttribute("data-carousel"));
  if (!track) return;
  var card = track.querySelector(".card");
  var step = card ? card.getBoundingClientRect().width + 16 : 240;
  var direction = button.getAttribute("data-dir") === "prev" ? -1 : 1;
  track.scrollBy({ left: direction * step * 2, behavior: "smooth" });
});
