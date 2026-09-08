document.querySelector('#export').addEventListener('click', async () => {
  const status = document.querySelector('#status')
  try {
    const cookies = await chrome.cookies.getAll({})
    const url = URL.createObjectURL(new Blob([JSON.stringify({ cookies })], { type: 'application/json' }))
    await chrome.downloads.download({ url, filename: 'marvi-cookies.json', saveAs: true })
    status.textContent = `${cookies.length} cookies exported. Import this JSON file in Marvi's Browser profiles.`
  } catch { status.textContent = 'Export did not finish. Check Chrome permissions and try again.' }
})
