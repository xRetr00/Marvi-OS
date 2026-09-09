param([string]$ResultPath)
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Marvi Computer Qualification'
$form.Width = 520
$form.Height = 260
$inputBox = New-Object System.Windows.Forms.TextBox
$inputBox.AccessibleName = 'Fixture input'
$inputBox.Location = New-Object System.Drawing.Point(25,25)
$inputBox.Width = 420
$button = New-Object System.Windows.Forms.Button
$button.Text = 'Save fixture'
$button.AccessibleName = 'Save fixture'
$button.Location = New-Object System.Drawing.Point(25,75)
$button.Width = 180
$button.Add_Click({ [System.IO.File]::WriteAllText($ResultPath, $inputBox.Text) })
$form.Controls.Add($inputBox)
$form.Controls.Add($button)
[void]$form.ShowDialog()
