//! Model-independent semantic retrieval boundary.

use crate::error::Result;

/// Produces an embedding using an explicitly configured provider.
pub trait Embedder {
    /// Return a finite, nonempty vector or an explicit provider failure.
    fn embed(&self, text: &str) -> Result<Vec<f32>>;
}
