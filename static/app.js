const startStudyButton = document.getElementById('start-study');
const studySection = document.getElementById('study-mode');

if (startStudyButton && studySection) {
  startStudyButton.addEventListener('click', () => {
    studySection.classList.toggle('active');
    startStudyButton.textContent = studySection.classList.contains('active') ? 'Hide study session' : 'Start study';
  });
}
