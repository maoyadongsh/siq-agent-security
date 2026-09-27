package main

func windowsTaskHelpRequested(command string, args []string) bool {
	return (command == "task-start" || command == "task-stop") && len(args) == 1 && (args[0] == "--help" || args[0] == "-h")
}
