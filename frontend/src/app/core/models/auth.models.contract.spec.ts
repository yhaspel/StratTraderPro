/**
 * Contract test: the hand-written auth models in `auth.models.ts` must stay
 * structurally in sync with the OpenAPI-generated types in `generated/schema.ts`.
 *
 * Failures show up at compile time — `ng test` will fail to compile this spec
 * if the shapes drift. The runtime `it()` block exists only so the failure
 * surfaces as a named test in reports.
 *
 * Regenerate via `npm run schema:types` (or `make schema`) after any backend
 * schema change, then run `ng test` to catch drift.
 */
import type {
  ApiEnvelope,
  ApiError,
  AuthTokenPair,
  AuthUser,
} from './auth.models';
import type { components } from '../generated/schema';

type SchemaAuthUser = components['schemas']['AuthUser'];
type SchemaTokenPairData = components['schemas']['TokenPairData'];
type SchemaApiError = components['schemas']['ApiError'];
type SchemaTokenPairEnvelope = components['schemas']['TokenPairEnvelope'];
type SchemaErrorEnvelope = components['schemas']['ErrorEnvelope'];

/**
 * `Assignable<A, B>` resolves to `true` iff any `A` is a valid `B` — i.e.
 * `A` is structurally assignable to `B`. We use a bidirectional version below
 * to assert the two shapes are structurally equivalent.
 */
type Assignable<A, B> = A extends B ? true : false;
type Equivalent<A, B> = Assignable<A, B> extends true
  ? Assignable<B, A> extends true
    ? true
    : false
  : false;

/** Compile-time assertion helper — fails to typecheck if T is not `true`. */
type Assert<T extends true> = T;

// ---------------------------------------------------------------------------
// Assertions — each line below is a compile-time check.
// Drift → `ng test` fails to compile this file.
// ---------------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-unused-vars */

// AuthUser must match the schema's AuthUser exactly.
type _AuthUserMatches = Assert<Equivalent<AuthUser, SchemaAuthUser>>;

// ApiError must match — including the enum-constrained `code`.
// We only assert one-way (hand-written ⊇ schema) because the hand-written
// `code: string` is intentionally wider than the schema enum to avoid
// coupling frontend switch-cases to backend enum growth.
type _ApiErrorSchemaAssignableToOurs = Assert<Assignable<SchemaApiError, ApiError>>;

// AuthTokenPair must match the schema's TokenPairData.
type _AuthTokenPairMatches = Assert<Equivalent<AuthTokenPair, SchemaTokenPairData>>;

// Both schema envelope variants must fit into our union-shaped ApiEnvelope<T>.
// (Our ApiEnvelope is intentionally wider — both `data` and `error` are optional —
// so the hand-written parser can accept any response shape.)
type _TokenEnvelopeAccepted = Assert<Assignable<SchemaTokenPairEnvelope, ApiEnvelope<AuthTokenPair>>>;
type _ErrorEnvelopeAccepted = Assert<Assignable<SchemaErrorEnvelope, ApiEnvelope<AuthTokenPair>>>;

/* eslint-enable @typescript-eslint/no-unused-vars */

describe('auth.models contract with generated OpenAPI schema', () => {
  it('compiles — types are structurally aligned', () => {
    // A runtime sample that also exercises the types.
    const sampleUser: AuthUser = {
      id: '6f2e5a1d-0c9b-4b4e-8d6a-111111111111',
      email: 'trader@example.com',
      display_name: 'Jane Trader',
      is_verified: true,
    };
    const asSchema: SchemaAuthUser = sampleUser;
    const asOurs: AuthUser = asSchema;
    expect(asOurs.email).toBe(sampleUser.email);

    const envelope: ApiEnvelope<AuthTokenPair> = {
      data: {
        access: 'a',
        refresh: 'r',
        user: sampleUser,
        mfa_required: false,
      },
    };
    expect(envelope.data?.user.id).toBe(sampleUser.id);

    const err: ApiError = {
      code: 'INVALID_CREDENTIALS',
      message: 'Invalid email or password.',
    };
    expect(err.code).toBe('INVALID_CREDENTIALS');
  });
});
