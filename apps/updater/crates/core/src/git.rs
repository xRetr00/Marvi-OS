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
    Command::new("git")
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

pub fn current_commit(dir: &Path) -> Result<String, GitError> {
    run(dir, &["rev-parse", "HEAD"])
}

pub fn fetch_origin(dir: &Path) -> Result<(), GitError> {
    run(dir, &["fetch", "--prune", "origin"]).map(|_| ())
}

pub fn fetch_tags(dir: &Path) -> Result<(), GitError> {
    run(dir, &["fetch", "--tags", "--force", "origin"]).map(|_| ())
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
    let out = run(dir, &["ls-remote", "origin", &format!("refs/heads/{branch}")])?;
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
    Invalid(String),
}

/// Verify a tag's cryptographic signature (`git verify-tag`).
///
/// Classification matters: a *lightweight* tag or an *unsigned* annotated tag
/// is "no signature" (integrity rests on HTTPS + hash pinning), whereas a tag
/// whose signature is present but bad is a hard failure.
pub fn verify_tag(dir: &Path, tag: &str) -> Result<SignatureStatus, GitError> {
    let output = Command::new("git")
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
    let unsigned = ["no signature", "not a signed tag", "non-tag object", "not a tag"]
        .iter()
        .any(|m| lower.contains(m));
    if unsigned {
        Ok(SignatureStatus::Unsigned)
    } else {
        Ok(SignatureStatus::Invalid(combined.trim().to_string()))
    }
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
        &["clone", "--branch", refname, url, dest.to_str().unwrap_or_default()],
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
}
