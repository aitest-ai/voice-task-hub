# Voice task hub contributor rules

1. This is a public code-only prototype. Never commit private scripts, reference recordings, generated speech, credentials, rights documents, or model weights.
2. Run `python3 -m unittest discover -s experiments/voice-jobs/tests -v` and Python compilation before proposing changes.
3. Keep the production worker template disabled. Do not add self-hosted runners, inference, secret setup, external API calls, or automatic job execution without explicit owner approval.
4. Do not treat BreezyVoice as supporting emotions or speed parameters it does not implement. Do not promise accent preservation through an engine cascade.
5. Preserve immutable job identities, hashes, reference-transcript and rights-policy cache invalidation, bounded retries and mock-versus-real distinction.
6. Use branches and draft pull requests for subsequent changes. No automatic merges or deployments.
7. Public repository visibility is not a voice license or permission to disclose job contents. Changing visibility later cannot recall already published material.
