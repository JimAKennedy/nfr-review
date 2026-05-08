import java.util.List;

public class BadService {

    public void processData(List<String> items) {
        try {
            parseItems(items);
        } catch (Exception e) {
            // broad catch without rethrow
        }
    }

    public void logToStdout(String message) {
        System.out.println("DEBUG: " + message);
    }

    private void parseItems(List<String> items) throws Exception {
        if (items == null) {
            throw new Exception("null items");
        }
    }
}
