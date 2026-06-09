# binding: return a clear error for empty JSON body in ShouldBindJSON

Fixes #3936

`ShouldBindJSON` previously returned `io.EOF` when the request body was
empty, which made it impossible for callers to distinguish an empty body
from a truncated stream. This change wraps the empty-body case with a
descriptive sentinel error so middleware can return a 400 with a clear
message.

The fix lives entirely in `binding/json.go`. The decoder behaviour is
preserved for any non-empty body — only the empty-body path is rewritten.

## Tests

* Added `TestJSONBindingEmptyBody` in `binding/binding_body_test.go`,
  asserting the error is `errors.Is(err, binding.ErrEmptyJSONBody)`.
* Existing JSON binding tests still pass (`go test ./binding/...`).

## Notes

`ErrEmptyJSONBody` is exported because callers need to match on it. It
joins the existing exported error sentinels in the `binding` package.
