using System;
using System.Diagnostics;

namespace SampleApp
{
    public class BadLogging
    {
        public void WritesToConsole()
        {
            Console.WriteLine("Processing started");
            Console.Write("Step 1...");
            Console.WriteLine("Done");
        }

        public void WritesToDebug()
        {
            Debug.WriteLine("Debug info");
        }

        public void MixedOutput()
        {
            Console.Write("Enter name: ");
            Console.WriteLine("Result: 42");
            Debug.WriteLine("Trace: completed");
        }
    }
}
