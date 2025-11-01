# ADR 004: GraphQL Client Patterns in Go RPC

**Status:** Accepted
**Date:** 2025-10-30
**Decision Makers:** User, Claude

## Context

Initial GraphQL queries failed with `422 Unprocessable Entity` errors. There was no published documentation for GraphQL usage in Stash RPC plugins.

## Problem

### Initial Errors:
```
Failed to trigger metadata scan: Message: 422 Unprocessable Entity
Failed to find 'Subtitled' tag: Message: 422 Unprocessable Entity
```

### Root Causes:
1. **Wrong return types**: Using custom structs instead of matching GraphQL schema
2. **Wrong parameter types**: Using `graphql.String` for IDs instead of `graphql.ID`
3. **Wrong query syntax**: Trying to query `findTag(name: $name)` when only `findTag(id: $id)` exists
4. **Inline input maps**: Using `map[string]interface{}` instead of proper structs

## Decision

Follow the pattern from Stash's example code (`pkg/plugin/examples/common/graphql.go`) with strict type matching.

## Solution Patterns

### Pattern 1: Use GraphQL Types

**❌ Wrong:**
```go
var mutation struct {
    MetadataScan ScanMetadata `graphql:"metadataScan(input: $input)"`
}
```

**✅ Correct:**
```go
var mutation struct {
    MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
}
```

**Rationale**: Schema shows `metadataScan(input: ScanMetadataInput!): ID!` - returns a string, not a complex object.

### Pattern 2: Use graphql.ID for IDs

**❌ Wrong:**
```go
type SceneUpdateInput struct {
    ID     graphql.String   `json:"id"`
    TagIds []graphql.String `json:"tag_ids"`
}
```

**✅ Correct:**
```go
type SceneUpdateInput struct {
    ID     graphql.ID   `json:"id"`
    TagIds []graphql.ID `json:"tag_ids"`
}
```

**Rationale**: GraphQL `ID!` type maps to `graphql.ID`, not `graphql.String`.

### Pattern 3: Use Proper Input Structs

**❌ Wrong:**
```go
variables := map[string]interface{}{
    "input": map[string]interface{}{
        "id":      graphql.String(sceneID),
        "tag_ids": tagIDs,
    },
}
```

**✅ Correct:**
```go
input := SceneUpdateInput{
    ID:     graphql.ID(sceneID),
    TagIds: tagIDs,
}

variables := map[string]interface{}{
    "input": input,
}
```

**Rationale**: Input structs with `json` tags ensure proper serialization.

### Pattern 4: Check Query Signatures

**❌ Wrong:**
```go
var tagQuery struct {
    FindTag *struct {
        ID graphql.String
    } `graphql:"findTag(name: $tagName)"`
}
```

**✅ Correct:**
```go
var tagQuery struct {
    AllTags []TagFragment `graphql:"allTags"`
}

// Then filter by name in code
for _, tag := range tagQuery.AllTags {
    if tag.Name == "Subtitled" {
        subtitledTagID = tag.ID
        break
    }
}
```

**Rationale**: Schema shows `findTag(id: ID!)` - only takes ID, not name. Use `allTags` to search by name.

### Pattern 5: Use Fragment Structs

**❌ Wrong:**
```go
var sceneQuery struct {
    FindScene struct {
        Tags []struct {
            ID graphql.String
        }
    } `graphql:"findScene(id: $sceneId)"`
}
```

**✅ Correct:**
```go
type TagFragment struct {
    ID   graphql.ID `json:"id" graphql:"id"`
    Name string     `json:"name" graphql:"name"`
}

type SceneFragment struct {
    ID   graphql.ID     `json:"id" graphql:"id"`
    Tags []*TagFragment `json:"tags" graphql:"tags"`
}

var sceneQuery struct {
    FindScene *SceneFragment `graphql:"findScene(id: $sceneId)"`
}
```

**Rationale**: Reusable fragments are cleaner and more maintainable.

### Pattern 6: Use Named Types for Type Reflection (Critical)

**❌ Wrong:**
```go
// Anonymous map - library can't reflect on type
variables := map[string]interface{}{
    "filter": map[string]interface{}{
        "per_page": 10,
    },
}
// Generates: query ($filter:!) {  // MISSING TYPE!
```

**❌ Wrong:**
```go
// Anonymous slice - library can't determine element type
args := []*PluginArgInput{{...}}
variables := map[string]interface{}{
    "args": args,
}
// Generates: mutation ($args:[!]!) {  // MISSING TYPE!
```

**✅ Correct:**
```go
// Named struct type - library can reflect
filterInput := &FindFilterType{
    PerPage: &graphql.Int(10),
}
variables := map[string]interface{}{
    "filter": filterInput,
}
// Generates: query ($filter: FindFilterType!) {  // CORRECT!
```

**✅ Correct:**
```go
// Named type alias for custom scalar
type Map map[string]interface{}

argsMap := &Map{
    "mode": "test",
    "value": 123,
}
variables := map[string]interface{}{
    "args_map": argsMap,
}
// Generates: mutation ($args_map: Map) {  // CORRECT!
```

**✅ Correct:**
```go
// Named type alias for slice
type PluginArgs []*PluginArgInput

args := &PluginArgs{{...}}
variables := map[string]interface{}{
    "args": args,
}
// Generates: mutation ($args: [PluginArgInput!]!) {  // CORRECT!
```

**Rationale**: The hasura/go-graphql-client uses **Go type reflection** to generate GraphQL type declarations. It inspects the Go type name to determine the corresponding GraphQL type. Anonymous types (plain maps/slices) have no type name, so the library cannot generate the correct GraphQL type declaration.

**Rule of Thumb:**
- For **GraphQL scalar types** (String, Int, ID, Boolean): Use `graphql.X` wrapper types directly
- For **GraphQL input object types**: Define a named Go struct and pass a pointer
- For **GraphQL custom scalars** (Map): Define a named type alias and pass a pointer
- For **GraphQL list types**: Define a named type alias and pass a pointer
- For **Go primitives** in variables: Wrap in appropriate `graphql.X` type

## Implementation Checklist

When adding new GraphQL queries/mutations:

1. ✅ Check GraphQL schema for exact signature
2. ✅ Match return type exactly (use `graphql.ID`, `graphql.String`, etc.)
3. ✅ Use `graphql.ID` for all ID fields
4. ✅ Create input structs with `json` tags
5. ✅ Use fragment structs for reusable types
6. ✅ **CRITICAL**: Pass pointers to named types for all variables (never anonymous maps/slices)
7. ✅ For custom scalars/collections: Create named type alias
8. ✅ Use `graphql` types in variable values (e.g., `graphql.ID(sceneID)`)

## Example: Complete Pattern

```go
// 1. Define input/fragment structs
type ScanMetadataInput struct {
    Paths []string `json:"paths"`
}

type TagFragment struct {
    ID   graphql.ID `json:"id" graphql:"id"`
    Name string     `json:"name" graphql:"name"`
}

// 2. Define query/mutation with proper return type
var mutation struct {
    MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
}

// 3. Create input instance
input := ScanMetadataInput{
    Paths: []string{captionPath},
}

// 4. Pass as variable
variables := map[string]interface{}{
    "input": input,
}

// 5. Execute
ctx := context.Background()
err := client.Mutate(ctx, &mutation, variables)

// 6. Extract result
jobID := string(mutation.MetadataScan)
```

## Debugging Tips

1. **Check schema first**: Always verify query/mutation signature in GraphQL schema
2. **Match types exactly**: `ID!` = `graphql.ID`, `String!` = `graphql.String`
3. **Use fragments**: Reusable structs prevent duplication
4. **Add tags**: Both `json` and `graphql` tags ensure proper serialization

## Consequences

### Positive:
- Type-safe GraphQL queries
- Compile-time error checking
- Reusable fragment structs
- Follows Stash's patterns

### Negative:
- Requires understanding GraphQL schema
- More boilerplate code
- Must manually sync with schema changes

## References

- [hasura/go-graphql-client](https://github.com/hasura/go-graphql-client)
- Stash example: `pkg/plugin/examples/common/graphql.go`
- Stash schema: `graphql/schema/schema.graphql`
