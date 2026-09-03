//! Thin wrappers over the `git` binary.
//!
//! Marvi OS ships as a git checkout, so `git` is a hard dependency of the
//! install/update path. Shelling out (rather than binding libgit2) keeps the
//! updater binary small and makes its behaviour identical to what a human
//! would run, which matters for a process that mutates a user's installation.

use std::fmt;
use std::path::Path;
use std::process::Command;

use crate::util::no_window;

/// A failed git invocation, carrying the offending command and its stderr so
/// the caller can produce an actionable message.
#[derive(Debug, Clone)]
pub struct GitError {
    pub command: String,
    pub stderr: String,
}

impl GitError {
    fn new(command: &str, stderr: String) -> Self {
        GitError {
            command: command.to_string(),
            stderr: stderr.trim().to_string(),
        }
    }
}

impl fmt::Display for GitError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.stderr.is_empty() {
            write!(f, "`git {}` failed", self.command)
        } else {
            write!(f, "`git {}` failed: {}", self.command, self.stderr)
        }
    }
}

impl std::error::Error for GitError {}

/// Run `git <args>` in `cwd`, returning trimmed stdout. Errors carry stderr.
pub fn run(cwd: &Path, args: &[&str]) -> Result<String, GitError> {
    let output = no_window(&mut Command::new("git"))
        .args(args)
        .current_dir(cwd)
        .output()
        .map_err(|e| GitError::new(&args.join(" "), e.to_string()))?;
    if !output.status.success() {
        return Err(GitError::new(
            &args.join(" "),
            String::from_utf8_lossy(&output.stderr).to_string(),
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// Run git but tolerate a non-zero exit (callers inspect the status code).
/// Used for checks where failure is an expected, non-fatal outcome.
pub fn run_status(cwd: &Path, args: &[&str]) -> Result<std::process::ExitStatus, GitError> {
    no_window(&mut Command::new("git"))
        .args(args)
        .current_dir(cwd)
        .status()
        .map_err(|e| GitError::new(&args.join(" "), e.to_string()))
}

/// True when `dir` is (or is inside) a usable git work tree.
pub fn is_work_tree(dir: &Path) -> bool {
    run_status(dir, &["rev-parse", "--is-inside-work-tree"])
        .map(|s| s.success())
        .unwrap_or(false)
}

/// True when the working tree has uncommitted changes (tracked or untracked).
pub fn is_dirty(dir: &Path) -> Result<bool, GitError> {
    let status = run(dir, &["status", "--porcelain"])?;
    Ok(!status.is_empty())
}

/// What is dirty, by path, so a message can name it instead of gesturing.
///
/// "Local changes present" is true and useless: it does not say which files,
/// so it cannot say whether they matter, and the only way to find out is to
/// open a terminal in a directory most people do not know they have.
pub fn dirty_files(dir: &Path) -> Result<Vec<String>, GitError> {
    let status = run(dir, &["status", "--porcelain"])?;
    // Split on the status field rather than at a fixed column. Porcelain puts
    // the path at index 3, but `run` trims its output, and trimming eats the
    // leading space of `" M f.txt"` -- so column 3 of the first line lands
    // mid-filename and reports `.txt`. Found by a test that asserted the
    // actual name instead of merely that something was named.
    Ok(status
        .lines()
        .filter_map(|line| line.trim_start().split_once(char::is_whitespace))
        .map(|(_status, path)| path.trim().to_string())
        .filter(|path| !path.is_empty())
        .collect())
}

/// Put every local change somewhere safe and leave a clean tree behind.
///
/// Returns the stash commit, which is the whole point: a stash is not a
/// discard. `git stash show -p <sha>` prints the changes and `git stash apply
/// <sha>` puts them back, and both keep working after the update has moved
/// the branch on, because the commit is reachable from the stash reflog
/// regardless of what HEAD does afterwards.
///
/// `--include-untracked` because a half-finished copy into the install is
/// untracked, and that is the shape this actually takes in practice.
pub fn stash_everything(dir: &Path, label: &str) -> Result<String, GitError> {
    run(
        dir,
        &["stash", "push", "--include-untracked", "--message", label],
    )?;
    run(dir, &["rev-parse", "stash@{0}"])
}

pub fn current_commit(dir: &Path) -> Result<String, GitError> {
    run(dir, &["rev-parse", "HEAD"])
}

pub fn fetch_origin(dir: &Path) -> Result<(), GitError> {
    run(dir, &["fetch", "--prune", "origin"]).map(|_| ())
}

pub fn fetch_tags(dir: &Path) -> Result<(), GitError> {
    run(dir, &["fetch", "--tags", "--force", "origin"]).map(|_| ())
}

/// Where `origin` points. Used to work out which GitHub release to fetch the
/// updater from, so the URL follows the checkout rather than being a constant
/// that would be wrong for a fork.
pub fn remote_url(dir: &Path) -> Result<String, GitError> {
    run(dir, &["remote", "get-url", "origin"]).map(|out| out.trim().to_string())
}

/// List remote tag refs (`refs/tags/...`) via `ls-remote`, without mutating
/// the local repository. Read-only network operation for the check path.
pub fn ls_remote_tags(dir: &Path) -> Result<Vec<String>, GitError> {
    let out = run(dir, &["ls-remote", "--tags", "origin"])?;
    parse_ls_remote_tags(&out)
}

/// List tag names from an arbitrary remote URL (used by the installer before a
/// clone exists).
pub fn ls_remote_url_tags(url: &str, cwd: &Path) -> Result<Vec<String>, GitError> {
    let out = run(cwd, &["ls-remote", "--tags", url])?;
    parse_ls_remote_tags(&out)
}

fn parse_ls_remote_tags(out: &str) -> Result<Vec<String>, GitError> {
    Ok(out
        .lines()
        .filter_map(|line| {
            let (_, name) = line.split_once('\t')?;
            let name = name.trim_end_matches("^{}");
            let tag = name.strip_prefix("refs/tags/")?;
            Some(tag.to_string())
        })
        .collect())
}

/// Resolve the remote tip of `refs/heads/<branch>` without mutating local refs.
pub fn ls_remote_branch(dir: &Path, branch: &str) -> Result<Option<String>, GitError> {
    let out = run(
        dir,
        &["ls-remote", "origin", &format!("refs/heads/{branch}")],
    )?;
    Ok(out
        .lines()
        .next()
        .and_then(|line| line.split_once('\t').map(|(sha, _)| sha.trim().to_string()))
        .filter(|sha| !sha.is_empty()))
}

/// Resolve a ref to a commit SHA. `refname` may be a tag, branch, or SHA.
pub fn resolve_commit(dir: &Path, refname: &str) -> Result<String, GitError> {
    run(dir, &["rev-parse", &format!("{refname}^{{commit}}")])
}

/// The outcome of verifying a tag's signature. Distinguishes "valid", "no
/// signature" and "bad signature" so policy can be applied rather than
/// treating all failures identically.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SignatureStatus {
    Valid,
    Unsigned,
    /// Signed, but this machine cannot check it -- no allowed-signers file, or
    /// git not configured to use one. Distinct from [`Invalid`] on purpose: not
    /// knowing is not the same as knowing it is bad, and conflating them turned
    /// a missing config file into a permanently blocked update.
    ///
    /// [`Invalid`]: SignatureStatus::Invalid
    Unverifiable(String),
    Invalid(String),
}

/// Verify a tag's cryptographic signature (`git verify-tag`).
///
/// Classification matters: a *lightweight* tag or an *unsigned* annotated tag
/// is "no signature" (integrity rests on HTTPS + hash pinning), whereas a tag
/// whose signature is present but bad is a hard failure.
pub fn verify_tag(dir: &Path, tag: &str) -> Result<SignatureStatus, GitError> {
    // The signers file ships in the checkout, so point git at it rather than
    // requiring every user to have configured one. Git has no default location
    // for it and errors out without one.
    //
    // What this is worth: it proves the tag was signed by the key in the
    // checkout you already have, so a tampered tag on the remote is caught. It
    // does not protect against a checkout that was already replaced wholesale
    // -- that trust comes from HTTPS and from the original install.
    let signers = dir.join(".github").join("allowed_signers");
    let mut command = Command::new("git");
    if signers.is_file() {
        command.args([
            "-c",
            &format!("gpg.ssh.allowedSignersFile={}", signers.display()),
        ]);
    }
    let output = no_window(&mut command)
        .args(["verify-tag", tag])
        .current_dir(dir)
        .output()
        .map_err(|e| GitError::new(&format!("verify-tag {tag}"), e.to_string()))?;
    let combined = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    if output.status.success() {
        return Ok(SignatureStatus::Valid);
    }
    let lower = combined.to_ascii_lowercase();
    let unsigned = [
        "no signature",
        "not a signed tag",
        "non-tag object",
        "not a tag",
    ]
    .iter()
    .any(|m| lower.contains(m));
    if unsigned {
        return Ok(SignatureStatus::Unsigned);
    }
    // "gpg.ssh.allowedSignersFile needs to be configured and exist for ssh
    // signature verification" -- git saying it lacks the means to check, not
    // that the check failed. This is what an older checkout says about every
    // signed tag, because the signers file only arrives with the update it is
    // refusing to install.
    let unverifiable = ["allowedsignersfile", "gpg failed to execute", "gpg.program"]
        .iter()
        .any(|m| lower.contains(m));
    if unverifiable {
        return Ok(SignatureStatus::Unverifiable(combined.trim().to_string()));
    }
    Ok(SignatureStatus::Invalid(combined.trim().to_string()))
}

/// Number of commits in `target` that are not reachable from `base`
/// (`git rev-list --count base..target`).
pub fn commit_count_behind(dir: &Path, base: &str, target: &str) -> Result<u64, GitError> {
    let out = run(dir, &["rev-list", "--count", &format!("{base}..{target}")])?;
    out.trim().parse::<u64>().map_err(|_| GitError {
        command: format!("rev-list --count {base}..{target}"),
        stderr: format!("unparseable count: {out}"),
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommitSummary {
    pub sha: String,
    pub summary: String,
    pub author: String,
    pub at: u64,
}

/// A bounded newest-first changelog for `base..target`.
///
/// Record/field separators are ASCII controls that cannot occur in a commit
/// summary or author name, avoiding locale-dependent parsing and extra git
/// invocations per row.
pub fn commits_between(
    dir: &Path,
    base: &str,
    target: &str,
    limit: usize,
) -> Result<Vec<CommitSummary>, GitError> {
    let range = format!("{base}..{target}");
    let max_count = format!("--max-count={}", limit.min(50));
    let out = run(
        dir,
        &[
            "log",
            "--no-decorate",
            "--format=%H%x1f%s%x1f%an%x1f%ct%x1e",
            &max_count,
            &range,
        ],
    )?;

    Ok(out
        .split('\u{1e}')
        .filter_map(|record| {
            let mut fields = record.trim().split('\u{1f}');
            let sha = fields.next()?.trim();
            let summary = fields.next()?.trim();
            let author = fields.next()?.trim();
            let at = fields.next()?.trim().parse::<u64>().ok()?;
            (!sha.is_empty() && !summary.is_empty()).then(|| CommitSummary {
                sha: sha.to_string(),
                summary: summary.to_string(),
                author: author.to_string(),
                at,
            })
        })
        .collect())
}

pub fn merge_ff_only(dir: &Path, target: &str) -> Result<(), GitError> {
    run(dir, &["merge", "--ff-only", target]).map(|_| ())
}

pub fn checkout(dir: &Path, target: &str) -> Result<(), GitError> {
    run(dir, &["checkout", "--quiet", target]).map(|_| ())
}

pub fn reset_hard(dir: &Path, commit: &str) -> Result<(), GitError> {
    run(dir, &["reset", "--hard", commit]).map(|_| ())
}

/// Clone `url` into `dest`, checking out `refname` (tag or branch). Full clone
/// so the resulting checkout can self-update over time.
pub fn clone(url: &str, refname: &str, dest: &Path) -> Result<(), GitError> {
    run(
        dest.parent().unwrap_or(dest),
        &[
            "clone",
            "--branch",
            refname,
            url,
            dest.to_str().unwrap_or_default(),
        ],
    )
    .map(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    fn init_repo() -> (PathBuf, tempfile::TempDir) {
        let dir = tempfile::TempDir::new().unwrap();
        let repo = dir.path().join("repo");
        fs::create_dir(&repo).unwrap();
        run(&repo, &["init", "-b", "main"]).unwrap();
        run(&repo, &["config", "user.email", "test@example.com"]).unwrap();
        run(&repo, &["config", "user.name", "Test"]).unwrap();
        fs::write(repo.join("f.txt"), "1").unwrap();
        run(&repo, &["add", "f.txt"]).unwrap();
        run(&repo, &["commit", "-m", "init"]).unwrap();
        (repo, dir)
    }

    #[test]
    fn detects_work_tree_and_dirty_state() {
        let (repo, _dir) = init_repo();
        assert!(is_work_tree(&repo));
        assert!(!is_dirty(&repo).unwrap());

        fs::write(repo.join("f.txt"), "changed").unwrap();
        assert!(is_dirty(&repo).unwrap());

        fs::write(repo.join("untracked.txt"), "x").unwrap();
        assert!(is_dirty(&repo).unwrap());
    }

    #[test]
    fn current_commit_is_a_sha() {
        let (repo, _dir) = init_repo();
        let sha = current_commit(&repo).unwrap();
        assert_eq!(sha.len(), 40);
        assert!(sha.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn commit_changelog_is_bounded_and_structured() {
        let (repo, _dir) = init_repo();
        let base = current_commit(&repo).unwrap();
        fs::write(repo.join("f.txt"), "2").unwrap();
        run(&repo, &["add", "f.txt"]).unwrap();
        run(
            &repo,
            &["commit", "-m", "feat(updater): show commit details"],
        )
        .unwrap();

        let commits = commits_between(&repo, &base, "HEAD", 12).unwrap();

        assert_eq!(commits.len(), 1);
        assert_eq!(commits[0].summary, "feat(updater): show commit details");
        assert_eq!(commits[0].author, "Test");
        assert_eq!(commits[0].sha.len(), 40);
        assert!(commits[0].at > 0);
    }
}

#[cfg(test)]
mod signature_tests {
    use super::*;

    /// A signed tag in a checkout that has no allowed-signers file. This is
    /// exactly what a machine installed before the signers file existed sees,
    /// and it used to abort the update with "invalid signature" -- which is
    /// both wrong and unrecoverable, since the file only arrives with the
    /// update being refused.
    #[test]
    fn a_signature_we_cannot_check_is_not_a_bad_signature() {
        let tmp = tempfile::TempDir::new().unwrap();
        let dir = tmp.path();
        let git = |args: &[&str]| {
            std::process::Command::new("git")
                .args(args)
                .current_dir(dir)
                .env("GIT_CONFIG_GLOBAL", "/dev/null")
                .env("GIT_CONFIG_SYSTEM", "/dev/null")
                .output()
                .unwrap()
        };
        git(&["init", "-b", "main"]);
        git(&["config", "user.email", "t@example.com"]);
        git(&["config", "user.name", "T"]);
        git(&["commit", "-m", "c", "--allow-empty"]);

        // A key made here, so the test needs nothing from the machine.
        let key = dir.join("k");
        std::process::Command::new("ssh-keygen")
            .args(["-t", "ed25519", "-N", "", "-C", "test", "-f"])
            .arg(&key)
            .output()
            .unwrap();
        git(&["config", "gpg.format", "ssh"]);
        git(&[
            "config",
            "user.signingkey",
            &format!("{}.pub", key.display()),
        ]);
        let tagged = git(&["tag", "-s", "v1.0.0", "-m", "v1.0.0"]);
        assert!(tagged.status.success(), "could not create a signed tag");

        // No .github/allowed_signers anywhere: git cannot check it.
        assert!(!dir.join(".github/allowed_signers").exists());

        match verify_tag(dir, "v1.0.0").unwrap() {
            SignatureStatus::Unverifiable(_) => {}
            other => panic!("expected Unverifiable, got {other:?} -- this blocks the update"),
        }
    }

    /// And with the signers file present, the same tag verifies -- so the
    /// relaxation above did not quietly turn verification off.
    #[test]
    fn the_signers_file_in_the_checkout_is_used() {
        let tmp = tempfile::TempDir::new().unwrap();
        let dir = tmp.path();
        let git = |args: &[&str]| {
            std::process::Command::new("git")
                .args(args)
                .current_dir(dir)
                .env("GIT_CONFIG_GLOBAL", "/dev/null")
                .env("GIT_CONFIG_SYSTEM", "/dev/null")
                .output()
                .unwrap()
        };
        git(&["init", "-b", "main"]);
        git(&["config", "user.email", "t@example.com"]);
        git(&["config", "user.name", "T"]);
        git(&["commit", "-m", "c", "--allow-empty"]);

        let key = dir.join("k");
        std::process::Command::new("ssh-keygen")
            .args(["-t", "ed25519", "-N", "", "-C", "test", "-f"])
            .arg(&key)
            .output()
            .unwrap();
        git(&["config", "gpg.format", "ssh"]);
        git(&[
            "config",
            "user.signingkey",
            &format!("{}.pub", key.display()),
        ]);
        git(&["tag", "-s", "v1.0.0", "-m", "v1.0.0"]);

        let public = std::fs::read_to_string(format!("{}.pub", key.display())).unwrap();
        std::fs::create_dir_all(dir.join(".github")).unwrap();
        std::fs::write(
            dir.join(".github/allowed_signers"),
            format!("t@example.com namespaces=\"git\" {}", public.trim()),
        )
        .unwrap();

        assert_eq!(verify_tag(dir, "v1.0.0").unwrap(), SignatureStatus::Valid);
    }
}
