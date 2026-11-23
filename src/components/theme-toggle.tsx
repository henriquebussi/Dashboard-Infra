import { Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/components/theme-provider"

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="h-9 w-9 text-[#69796f] hover:bg-[#f0f5f1] dark:text-muted-foreground dark:hover:bg-accent"
      aria-label="Modo escuro"
      aria-pressed={dark}
      title={dark ? "Ativar modo claro" : "Ativar modo escuro"}
    >
      {dark ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  )
}
