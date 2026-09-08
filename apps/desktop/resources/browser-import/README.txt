Marvi Cookie Export — local only

1. Open chrome://extensions in the Chrome profile you want to export.
2. Enable Developer mode, choose Load unpacked, and select this folder.
3. Open Marvi Cookie Export from Chrome's extensions menu.
4. Choose Export this profile's cookies, then choose a local file destination.
5. In Marvi's Browser page, close the destination profile and choose Import cookie JSON.
6. Delete the exported JSON when you no longer need it. Remove this helper from Chrome if finished.

The helper uses Chrome's supported cookies API with permission you grant in Chrome.
It does not read or decrypt Chrome's database files, contact a cloud service,
or access saved passwords. For passwords, use Chrome Password Manager's CSV export
and Marvi's separate Import password CSV action.
