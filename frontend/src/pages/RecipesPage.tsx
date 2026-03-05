import { useEffect, useMemo, useState } from "react";
import { Alert } from "../components/ui/Alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { listRecipes, listRecipeStates, updateRecipeState } from "../api/workspace";
import { PageContainer } from "../layout/PageContainer";
import type { Recipe, WorkspaceRecipeState } from "../types/workspace";

export function RecipesPage() {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [states, setStates] = useState<WorkspaceRecipeState[]>([]);
  const [savingRecipeId, setSavingRecipeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listRecipes(), listRecipeStates()])
      .then(([recipeRows, stateRows]) => {
        setRecipes(recipeRows);
        setStates(stateRows);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load recipes"));
  }, []);

  const stateByRecipeId = useMemo(() => {
    const map = new Map<string, WorkspaceRecipeState>();
    for (const state of states) {
      map.set(state.recipe_id, state);
    }
    return map;
  }, [states]);

  async function toggleRecipe(recipe: Recipe, enabled: boolean) {
    setSavingRecipeId(recipe.id);
    setError(null);
    setMessage(null);
    try {
      const currentState = stateByRecipeId.get(recipe.id);
      const updated = await updateRecipeState(recipe.id, {
        enabled,
        config_json: currentState?.config_json ?? recipe.default_config_json
      });
      setStates((prev) => {
        const filtered = prev.filter((item) => item.recipe_id !== recipe.id);
        return [...filtered, updated];
      });
      setMessage(`Recipe ${enabled ? "enabled" : "disabled"}: ${recipe.name}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update recipe state");
    } finally {
      setSavingRecipeId(null);
    }
  }

  return (
    <PageContainer>
      <Card>
        <CardHeader>
          <CardTitle>Automation Recipes</CardTitle>
          <CardDescription>Enable turnkey workflows for channels, RAG, calendar, email, and lead capture.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {error && (
            <Alert title="Recipes Error" variant="danger">
              {error}
            </Alert>
          )}
          {message && (
            <Alert title="Updated" variant="success">
              {message}
            </Alert>
          )}

          {recipes.map((recipe) => {
            const state = stateByRecipeId.get(recipe.id);
            const enabled = state?.enabled ?? false;
            const saving = savingRecipeId === recipe.id;
            return (
              <article className="rounded border border-white/10 bg-white/5 p-4" key={recipe.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-white">{recipe.name}</h3>
                    <p className="mt-1 text-sm text-slate-300">{recipe.description}</p>
                    <p className="mt-2 text-xs text-slate-400">Key: {recipe.key}</p>
                  </div>
                  <button
                    className={`rounded px-3 py-2 text-sm font-medium ${enabled ? "bg-emerald-600 text-white" : "bg-slate-700 text-slate-100"}`}
                    disabled={saving}
                    onClick={() => void toggleRecipe(recipe, !enabled)}
                    type="button"
                  >
                    {saving ? "Saving..." : enabled ? "Enabled" : "Enable"}
                  </button>
                </div>
              </article>
            );
          })}
        </CardContent>
      </Card>
    </PageContainer>
  );
}
