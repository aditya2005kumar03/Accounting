document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash-close').forEach((button) => {
    button.addEventListener('click', () => button.closest('.flash')?.remove());
  });

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.dataset.confirm || 'Are you sure?')) event.preventDefault();
    });
  });

  const journalFile = document.getElementById('journal_file');
  const chartFile = document.getElementById('chart_file');
  if (journalFile) {
    journalFile.addEventListener('change', () => {
      const label = document.getElementById('journal-file-name');
      if (label) label.textContent = journalFile.files?.[0]?.name || 'No file selected · CSV up to 10 MB';
    });
  }
  if (chartFile) {
    chartFile.addEventListener('change', () => {
      const label = document.getElementById('chart-file-name');
      if (label) label.textContent = chartFile.files?.[0]?.name || 'No chart selected · Current chart will be used';
    });
  }
});
