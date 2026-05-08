import java.util.logging.Logger;

public class GoodService {

    private static final Logger logger = Logger.getLogger(GoodService.class.getName());

    public void processData(String data) {
        try {
            Integer.parseInt(data);
        } catch (NumberFormatException e) {
            logger.warning("Bad number: " + e.getMessage());
            throw e;
        }
    }
}
